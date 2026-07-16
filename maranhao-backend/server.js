const express = require('express');
const app = express();
const http = require('http').createServer(app);
const io = require('socket.io')(http);
const path = require('path');

app.get('/', (req, res) => res.sendFile(path.join(__dirname, 'index.html')));
app.get('/cozinha', (req, res) => res.sendFile(path.join(__dirname, 'cozinha.html')));
app.get('/entrega', (req, res) => res.sendFile(path.join(__dirname, 'entrega.html')));

io.on('connection', (socket) => {
    console.log('Alguém se conectou ao sistema Krikati');

    socket.on('novo_pedido', (dadosPedido) => {
        console.log('Pedido recebido:', dadosPedido);
        io.emit('pedido_para_cozinha', dadosPedido);
    });

    socket.on('pedido_pronto', (dadosPedido) => {
        console.log('Pedido pronto na cozinha:', dadosPedido);
        io.emit('pedido_para_entrega', dadosPedido);
    });
});

http.listen(3000, () => {
    console.log('Sistema Krikati rodando em http://localhost:3000');
});
