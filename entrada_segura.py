"""Entrada sem transporte e autenticação de eventos. Sem efeitos no import."""
import hashlib
import hmac
import re
from email_seguranca import bloquear_envios_no_contexto


def assinatura_meta_valida(raw, assinatura, segredo):
    if not segredo or not isinstance(assinatura, str) or not re.fullmatch(r'sha256=[0-9a-f]{64}', assinatura):
        return False
    esperado = 'sha256=' + hmac.new(segredo.encode(), raw, hashlib.sha256).hexdigest()
    return hmac.compare_digest(assinatura, esperado)


def interpretar_sem_saida(processador, interacao):
    with bloquear_envios_no_contexto():
        return processador(interacao)


def reconciliar_interacao(factory, processador, interacao):
    """Retry de interpretação explícito e serializado; nunca libera P0."""
    conn = factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ('gmail-entrada:'+str(interacao['id']),))
                cur.execute("SELECT estado FROM gmail_processamentos_seguros WHERE interacao_id=%s FOR UPDATE", (str(interacao['id']),))
                row = cur.fetchone()
                if row and row[0] == 'concluido':
                    return {'success': True, 'ja_processada': True}
                cur.execute("""INSERT INTO gmail_processamentos_seguros(interacao_id,estado,tentativas)
                    VALUES(%s,'pendente',1) ON CONFLICT(interacao_id) DO UPDATE SET
                    tentativas=gmail_processamentos_seguros.tentativas+1,atualizado_em=NOW()""", (str(interacao['id']),))
                try:
                    resultado = interpretar_sem_saida(processador, interacao)
                    if not resultado or not resultado.get('success'):
                        raise RuntimeError('interpretacao_nao_confirmada')
                except Exception as erro:
                    cur.execute("UPDATE gmail_processamentos_seguros SET estado='falhou',erro_tipo=%s,atualizado_em=NOW() WHERE interacao_id=%s", (type(erro).__name__,str(interacao['id'])))
                    return {'success': False, 'erro_tipo': type(erro).__name__}
                cur.execute("UPDATE gmail_processamentos_seguros SET estado='concluido',erro_tipo=NULL,atualizado_em=NOW() WHERE interacao_id=%s", (str(interacao['id']),))
                cur.execute("UPDATE interacoes_omnichannel SET processado_ia=TRUE WHERE id=%s", (str(interacao['id']),))
                return resultado
    finally:
        conn.close()


def encerrar_pesquisas_abandonadas(factory):
    """Expiração conservadora: preserva a pesquisa e registra estado anterior."""
    conn = factory()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute("""INSERT INTO pesquisas_abandonadas_auditoria(pesquisa_id,estado_anterior,iniciado_em)
                    SELECT id,status,iniciado_em FROM pesquisas_fase57
                    WHERE status='executando' AND iniciado_em < NOW()-INTERVAL '24 hours'
                    ON CONFLICT DO NOTHING""")
                cur.execute("""UPDATE pesquisas_fase57 SET status='erro',concluido_em=NOW(),
                    erro='execucao_abandonada_requer_nova_pesquisa'
                    WHERE status='executando' AND iniciado_em < NOW()-INTERVAL '24 hours'
                    AND EXISTS (SELECT 1 FROM pesquisas_abandonadas_auditoria a
                        WHERE a.pesquisa_id=pesquisas_fase57.id AND a.iniciado_em=pesquisas_fase57.iniciado_em)""")
    finally:
        conn.close()
