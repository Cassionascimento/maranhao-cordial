const fs=require('fs'),assert=require('assert');
const css=fs.readFileSync('maranhao-backend/app-shell.css','utf8');
assert(css.includes('linear-gradient(180deg,#07100b'));
assert(css.includes("content:'Intelligence'"));
assert(css.includes('grid-template-columns:repeat(auto-fit,minmax(190px,1fr))'));
assert(css.includes('@media(prefers-reduced-motion:reduce)'));
console.log('painel agentico UI: ok');
