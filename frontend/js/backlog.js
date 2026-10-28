/* Explicit reader access: a late fetch cannot open or repopulate a closed backlog. */
(function(root) {
  'use strict';
  class BacklogAccess {
    constructor() {this.opened=false;this.profileId=null;this.revision=0;}
    open(profileId) {this.opened=true;this.profileId=profileId;this.revision++;}
    close() {this.opened=false;this.profileId=null;this.revision++;}
    requestToken(profileId) {
      return this.opened && this.profileId===profileId ? {profileId,revision:this.revision} : null;
    }
    accepts(token,profileId) {
      return !!token && this.opened && token.revision===this.revision &&
        token.profileId===this.profileId && token.profileId===profileId;
    }
  }
  root.BacklogAccess=BacklogAccess;
  if(typeof module!=='undefined' && module.exports)module.exports=BacklogAccess;
})(globalThis);
