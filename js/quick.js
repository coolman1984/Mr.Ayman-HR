// Personal link page (/k/...): logs in by itself. Only a real browser runs this, so a chat preview or a
// virus scanner that looks at the link does not log anybody in.
const f = document.getElementById('go');
if (f) f.submit();
