const assert=require('node:assert/strict');
const source=require('node:fs').readFileSync(require('node:path').join(__dirname,'js/backlog.js'),'utf8');
const BacklogAccess=new Function(source+'\nreturn BacklogAccess;')();
let checks=0;
function test(name,fn){fn();checks++;console.log('PASS '+name);}
test('history cannot be requested on launch or on a new subtitle',()=>{
  const reader=new BacklogAccess();assert.equal(reader.opened,false);
  for(let n=0;n<50;n++)assert.equal(reader.requestToken('seabed'),null);
});
test('explicit opening permits only this game',()=>{
  const reader=new BacklogAccess();reader.open('seabed');
  assert(reader.accepts(reader.requestToken('seabed'),'seabed'));
  assert.equal(reader.requestToken('other'),null);
});
test('closing rejects a history response already in flight',()=>{
  const reader=new BacklogAccess();reader.open('seabed');const pending=reader.requestToken('seabed');
  reader.close();assert.equal(reader.accepts(pending,'seabed'),false);assert.equal(reader.opened,false);
});
test('reopening does not permit an earlier response to replace this reading',()=>{
  const reader=new BacklogAccess();reader.open('seabed');const old=reader.requestToken('seabed');
  reader.close();reader.open('seabed');assert.equal(reader.accepts(old,'seabed'),false);
});
test('a game switch cannot display the previous game history',()=>{
  const reader=new BacklogAccess();reader.open('seabed');const old=reader.requestToken('seabed');
  assert.equal(reader.accepts(old,'other'),false);
  reader.close();assert.equal(reader.requestToken('other'),null);
});
console.log(checks+' backlog access checks passed');
