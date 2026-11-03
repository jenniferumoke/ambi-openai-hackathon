document.querySelector('form').addEventListener('submit', async event => {
  event.preventDefault(); const field = document.querySelector('#key'); const value = field.value; field.value = '';
  document.querySelector('button').disabled = true;
  try { await window.ambiLinux.submitKey(value); }
  catch { document.querySelector('#status').textContent = 'Setup did not finish. End active work and try again.'; document.querySelector('button').disabled = false; }
});
