from flask import Flask, request, send_from_directory
import os
import argparse
from tqdm import tqdm
from flask import jsonify
import csv
import numpy
from bling_fire_tokenizer import BlingFireTokenizer
import yaml

app = Flask(__name__, static_url_path='')
app.config['SEND_FILE_MAX_AGE_DEFAULT'] = 0

#
# data loading & prep
#

with open(os.environ.get("RUN_CONFIG"), 'r') as ymlfile:
    yaml_cfg = yaml.load(ymlfile)

runs = yaml_cfg["runs"]

max_doc_char_length = 100_000
 
def load_qrels(path):
    with open(path,'r') as f:
        qids_to_relevant_passageids = {}
        for l in f:
            try:
                l = l.strip().split()
                qid = l[0]
                if l[3] != "0":
                    if qid not in qids_to_relevant_passageids:
                        qids_to_relevant_passageids[qid] = []
                    qids_to_relevant_passageids[qid].append(l[2].strip())
            except:
                raise IOError('\"%s\" is not valid format' % l)
        return qids_to_relevant_passageids

qrels = []
clusters = []
collection = []
queries = []
queries_with_stats = []
secondary_model = []
secondary_qd = []

collection_cache = {}
queries_cache = {}

for run_id, run in enumerate(runs):

    qrels.append(load_qrels(run["qrels"]))

    with open(run["cluster-stats"],"r") as csv_file:
        cluster_csv = csv.DictReader(csv_file)
        _clusters = {}
        for row in cluster_csv:
            _clusters[row["cluster"]] = dict(row)
            _clusters[row["cluster"]]["queries"] = []

    with open(run["queries"],"r") as csv_file:
        query_csv = csv.DictReader(csv_file)
        _queries = {}
        _queries_with_stats = {}
        for row in query_csv:
            _clusters[row["cluster"]]["queries"].append(dict(row))
            _queries[row["qid"]] = row["text"]
            _queries_with_stats[row["qid"]] = dict(row)
    queries.append(_queries)
    queries_with_stats.append(_queries_with_stats)
    clusters.append(_clusters)

    if run["collection"] in collection_cache:
        collection.append(collection_cache[run["collection"]])
    else:
        _collection = {} # int id -> full line dictionary
        with open(run["collection"],"r",encoding="utf8") as collection_file:
            for line in tqdm(collection_file):
                ls = line.split("\t") # id<\t>text ....
                _id = ls[1]
                _collection[_id] = ls[3].rstrip()[:max_doc_char_length]
        collection_cache[run["collection"]]= _collection
        collection.append(_collection)

    secondary = numpy.load(run["secondary-output"], allow_pickle = True)
    secondary_model.append(secondary.get("model_data")[()])
    secondary_qd.append(secondary.get("qd_data")[()])

    #filter clusters according to the queries that are in the secondary output
    qids_in_secondary_data = secondary_qd[run_id].keys()
    for cluster_id in clusters[run_id].keys():
        new_query_list = []
        for qidx, query in enumerate(clusters[run_id][cluster_id]["queries"]):
            if query["qid"] in qids_in_secondary_data:
               new_query_list.append(query)
        clusters[run_id][cluster_id]["queries"] = new_query_list
    
    queries_to_remove = []
    for qid in queries_with_stats[run_id].keys():
        if not qid in qids_in_secondary_data:
            queries_to_remove.append(qid)

    for qid_remove in queries_to_remove:
        queries_with_stats[run_id].pop(qid_remove)


    if run["run-info"]["score_type"]=="tk" or run["run-info"]["score_type"]=="fk":
        run["run-info"]["model_weights_log_len_mix"] = secondary.get("model_data")[()]["dense_comb_weight"][0].tolist()

import gc
gc.collect()

#
# api endpoints
#
@app.route('/dist/<path:path>')
def send_dist(path):
    return send_from_directory('dist', path)

@app.route("/")
def main():
    return send_from_directory('', 'index.html')

@app.route("/run-info")
def run_info():
    return jsonify(runs=[r["run-info"] for r in runs])

@app.route("/evaluated-queries/<run>")
def all_queries(run):
    return jsonify(clusters=clusters[int(run)])

@app.route("/query/<run>/<qid>")
def query(qid,run):
    run = int(run)
    documents = []

    for doc in secondary_qd[run][qid]:

        documents.append(get_document_info(runs[run]["run-info"]["score_type"],qid,doc,secondary_qd[run][qid][doc],run))

    return jsonify(documents=documents)

#
# helper methods
#
tokenizer = BlingFireTokenizer()

def analyze_weighted_param_1D(name,values, param_weight,bias=None,last_x=5):
    #print(name, ": value * weight + bias")
    rolling_sum = 0
    rolling_sum_after_x = 0

    kernels = {}
    after_x = len(values) - last_x

    for i,val in enumerate(values):
        param = param_weight[i]
        if i < after_x:
            kernels[i] = (float(val),float(param))
        #print("["+str(i)+"]", str(val) + " * "+str(param) + " = "+ str(val*param))
        rolling_sum += val*param

        if i >= after_x:
            rolling_sum_after_x += val*param


    #if bias != None:
        #print("Sum:",rolling_sum + bias)
        #print("Sum(>="+str(after_x)+")",rolling_sum_after_x + bias)
    #else:
        #print("Sum:",rolling_sum)
        #print("Sum(>="+str(after_x)+")",rolling_sum_after_x)
    
    #print("-----------")
    if bias != None:
        rolling_sum = rolling_sum + bias
        rolling_sum_after_x = rolling_sum_after_x + bias
    return (kernels, float(rolling_sum),float(rolling_sum_after_x))


def get_document_info(score_type,qid,did,secondary_info,run):

    document_info = {"id":float(did),"score":float(secondary_info["score"]),"judged_relevant": did in qrels[run][qid]}

    if score_type == "tk" or score_type == "fk":
        document_info["val_log"] = analyze_weighted_param_1D("log-kernels",secondary_info["per_kernel"],secondary_model[run]["dense_weight"][0],last_x=runs[run]["run-info"]["rest-kernels-last"])
        document_info["val_len"] = analyze_weighted_param_1D("len-norm-kernels",secondary_info["per_kernel_mean"],secondary_model[run]["dense_mean_weight"][0],last_x=runs[run]["run-info"]["rest-kernels-last"])
    if score_type == "knrm":
        document_info["val_log"] = analyze_weighted_param_1D("log-kernels",secondary_info["per_kernel"],secondary_model[run]["kernel_weight"][0],last_x=runs[run]["run-info"]["rest-kernels-last"])

    document_info["tokenized_query"] = tokenizer.tokenize(queries[run][qid])
    document_info["tokenized_document"] = tokenizer.tokenize(collection[run][did])

    #matches = []
    matches_per_kernel = []
    matches_per_kernel_strongest = []

    original_mm = numpy.transpose(secondary_info["cosine_matrix_masked"][:len(document_info["tokenized_query"]),:len(document_info["tokenized_document"])]).astype('float64') 

    kernel_transformed = numpy.exp(- pow(numpy.expand_dims(original_mm,2) - numpy.array(runs[run]["run-info"]["kernels_mus"]), 2) / (2 * pow(0.1, 2)))
    kernel_transformed_max_query_per_kernel = numpy.max(kernel_transformed,axis=1)

    #for t,token in enumerate(document_info["tokenized_document"]):
    #    #largest_sim = secondary_info["cosine_matrix_masked"][max_query_id_per_doc[t]][t]
#
    #    kernel_results = [0]*len(runs["run-info"]["kernels_mus"])
    #    #matches_per_doc = []
    #    for i,m in enumerate(runs["run-info"]["kernels_mus"]):
    #        for q in range(secondary_info["cosine_matrix_masked"].shape[0]):
    #            kernel_results[i] = float(max(kernel_results[i],(kernel_transformed[q][t][i])))
    #            #matches_per_doc.append(float(secondary_info["cosine_matrix_masked"][q][t]))
    #    
    #    #matches.append(matches_per_doc)
    #    matches_per_kernel.append(kernel_results)
    #    
    #    strongest_kernel = numpy.argmax(numpy.array(kernel_results),axis=0).tolist()
    #    matches_per_kernel_strongest.append(strongest_kernel)

    #print(secondary_info["cosine_matrix_masked"].dtype)
    #print(original_mm.dtype)
    #print(kernel_transformed.shape)
    #print(kernel_transformed.dtype)
    #print(original_mm)
    #print(numpy.around(original_mm,3).dtype)
    #print(numpy.around(original_mm,3).tolist())
    #print(numpy.around(kernel_transformed,3).dtype)
    document_info["matches"] = numpy.around(original_mm,3).tolist()
    document_info["matches_per_kernel"] = numpy.around(kernel_transformed,3).tolist()
    document_info["matches_per_kernel_max"] = numpy.around(kernel_transformed_max_query_per_kernel,3).tolist()


    #for q in range(len(document_info["tokenized_query"])):
    #    mq = []
    #    for d in range(len(document_info["tokenized_document"])):
    #        mq.append(float(secondary_info["cosine_matrix_masked"][q][d]))
    #    matches.append(mq)
    #document_info["matches"] = matches

    return document_info