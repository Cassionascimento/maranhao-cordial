/* Gmail institucional: acesso operacional direto. OAuth permanece disponível no backend para reconexão controlada, mas o botão da Central abre a caixa institucional. */
function conectarGmailP0() {
    const status = document.getElementById("gmailP0Status");
    if (!window.adminKeyAtual) {
        if (status) status.textContent = "Entre na Central com a chave administrativa.";
        return;
    }
    const gmail = "https://mail.google.com/mail/u/0/";
    const janela = window.open(gmail, "_blank", "noopener,noreferrer");
    if (!janela && status) {
        status.textContent = "O navegador bloqueou a nova aba. Permita pop-ups para abrir o Gmail.";
        return;
    }
    if (status) status.textContent = "Gmail institucional aberto em nova aba.";
}

function prepararAcessoGmail() {
    const botao = document.querySelector('[onclick="conectarGmailP0()"]');
    if (botao) botao.textContent = "Abrir Gmail institucional";
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', prepararAcessoGmail);
else prepararAcessoGmail();
window.conectarGmailP0 = conectarGmailP0;
