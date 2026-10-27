import { MINUTE } from './domain.js';

export function initialState() {
  return {
    version:2,clock:Date.now(),cameras:[],workspaces:[],events:[],liveIntervals:[],backups:[],
    settings:{site:'',timezone:'Asia/Jakarta',start:'09:00',end:'17:00',breakStart:'12:00',breakEnd:'13:00',calendarRevision:1,detailDays:365,aggregateYears:3,backupDays:30},
    emptyHistory:true,persistence:'HEALTHY',step:0,
  };
}

export function effectiveWorkspace(workspace) {
  return {...workspace,liveState:'UNKNOWN',count:null,reason:'STARTUP'};
}

export function advanceState(state, minutes=1) {
  return {...state,clock:state.clock+minutes*MINUTE};
}

export function dataset(state) {
  return state.liveIntervals;
}
