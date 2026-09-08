const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const source = fs.readFileSync('maranhao-backend/experience-player.js', 'utf8');
test('player externo só é criado após escolha explícita, com listener único', () => {
 let callback, options, created = 0, replaced;
 const button = {dataset:{player:'https://www.youtube.com/embed/videoseries?list=test'},addEventListener(event,fn,opts){assert.equal(event,'click');callback=fn;options=opts;},replaceWith(frame){replaced=frame;}};
 const document = {querySelectorAll(){return [button];},createElement(tag){assert.equal(tag,'iframe');created++;return {setAttribute(){},focus(){}};}};
 vm.runInNewContext(source,{document});
 assert.equal(created,0);assert.equal(options.once,true);
 callback();assert.equal(created,1);assert.equal(replaced.src,button.dataset.player);
 assert.ok(replaced.title);assert.ok(!replaced.src.includes('autoplay=1'));
});
