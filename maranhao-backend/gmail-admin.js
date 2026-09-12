/* Extraído de admin.html sem alteração de lógica. Conexão Gmail institucional
   (P0): abre a janela de autorização e repassa a chave administrativa por
   postMessage. Ponte em window mantém o onclick inline existente funcionando. */
function conectarGmailP0() {
    const status = document.getElementById("gmailP0Status");
    const chave = window.adminKeyAtual;
    if (!chave) {
        status.textContent = "Entre na Central com a chave administrativa.";
        return;
    }
    const origemApi = "https://maranhao-cordial-api.onrender.com";
    const janela = window.open(origemApi + "/api/gmail/painel", "_blank", "width=640,height=760");
    if (!janela) {
        status.textContent = "Permita a abertura da janela para conectar o Gmail.";
        return;
    }
    status.textContent = "Conclua a autorização na janela do Gmail.";
    const receber = (evento) => {
        if (evento.origin !== origemApi || evento.source !== janela || evento.data?.tipo !== "gmail-p0-pronto") return;
        window.removeEventListener("message", receber);
        clearTimeout(prazo);
        janela.postMessage({tipo: "gmail-p0-autorizar", chave}, origemApi);
    };
    window.addEventListener("message", receber);
    const prazo = setTimeout(() => {
        window.removeEventListener("message", receber);
        status.textContent = "Conexão não iniciada. Feche a janela e tente novamente.";
    }, 60000);
}

window.conectarGmailP0 = conectarGmailP0;
