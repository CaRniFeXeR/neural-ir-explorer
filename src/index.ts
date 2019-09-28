import Vue from "vue";
import ExploreView from "./ExploreView.vue";
import SplashScreen from "./components/SplashScreen.vue";
import RunInfoBox from "./components/RunInfoBox.vue"
import "./global-styles.scss"
import '@fortawesome/fontawesome-free/css/all.css';

let v = new Vue({
    el: "#app",
    template: `
    <div>
        <header><div class="inner-header"><i class="fas fa-search"></i> neural-ir-explorer &ndash; <run-info-box @run-changed="(x) => {currentRun = x}" /></div></header>
        <splash-screen v-bind:run-info="currentRun" v-if="currentMainView == 'splash'" @all-done="currentMainView = 'explore'"/>
        <explore-view v-bind:run-info="currentRun" v-show="currentMainView == 'explore'"/>
        <footer><div class="inner-footer"> Made with <i class="fa fa-heart"></i> - Demo under review at ECIR </div></footer>
    </div>
    `,
    data(){
        return {
            currentRun:{},
            currentMainView:"splash",
        }
    },
    components: {
        ExploreView,
        SplashScreen,
        RunInfoBox
    },
});