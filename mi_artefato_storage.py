"""Interface abstrata de storage de artefatos (P5.X).

Fatiada para dentro de M1 porque um contrato de artefato não é testável
nem útil sem algum lugar real para guardar bytes -- M14 (governança de
storage) continua sendo o milestone que formaliza a decisão de produção,
mas a interface já nasce abstrata aqui para nunca acoplar mi_artefatos.py
a um mecanismo só.

Provider padrão reaproveita o único mecanismo de persistência de arquivo
já comprovado em produção neste projeto: BYTEA em Postgres, mesmo padrão
de `documentos_empresariais.conteudo` (ver P5X_AUDIT.md itens 6/15).
Nenhum object storage externo (S3 ou equivalente) está configurado --
por isso só existe um segundo provider de exemplo, `StorageNaoConfigurado`,
que nunca finge persistência: toda tentativa de uso levanta
`ErroStorageNaoConfigurado` explicitamente.
"""
import uuid


class ArtifactStorage:
    def salvar(self, conteudo: bytes, mime_type: str) -> str:
        raise NotImplementedError

    def ler(self, storage_uri: str):
        raise NotImplementedError

    def disponivel(self) -> bool:
        raise NotImplementedError


class ErroStorageNaoConfigurado(RuntimeError):
    pass


PREFIXO_POSTGRES_BLOB = 'pg-blob:'


class PostgresBlobStorage(ArtifactStorage):
    """LIVE -- reaproveita o cursor de escrita já aberto pelo chamador
    (mesma conexão/transação do INSERT em mi_artefatos), nunca abre uma
    segunda conexão só para o blob."""

    def __init__(self, cur):
        self.cur = cur

    def salvar(self, conteudo, mime_type):
        from psycopg2 import Binary
        blob_id = uuid.uuid4()
        self.cur.execute(
            "INSERT INTO mi_artefatos_blobs (id, conteudo, mime_type, tamanho_bytes) "
            "VALUES (%s,%s,%s,%s)",
            (str(blob_id), Binary(conteudo), mime_type, len(conteudo)),
        )
        return f'{PREFIXO_POSTGRES_BLOB}{blob_id}'

    def ler(self, storage_uri):
        if not storage_uri or not storage_uri.startswith(PREFIXO_POSTGRES_BLOB):
            raise ValueError('storage_uri_formato_invalido')
        blob_id = storage_uri[len(PREFIXO_POSTGRES_BLOB):]
        self.cur.execute("SELECT conteudo FROM mi_artefatos_blobs WHERE id=%s", (blob_id,))
        row = self.cur.fetchone()
        if not row:
            return None
        conteudo = row['conteudo'] if isinstance(row, dict) else row[0]
        return bytes(conteudo)

    def disponivel(self):
        return True


class StorageNaoConfigurado(ArtifactStorage):
    """Prova de que a interface funciona com mais de um provider, sem
    fingir persistência que não existe (M14 nunca finge storage)."""

    def salvar(self, conteudo, mime_type):
        raise ErroStorageNaoConfigurado('ArtifactStorage não configurado para este provider.')

    def ler(self, storage_uri):
        raise ErroStorageNaoConfigurado('ArtifactStorage não configurado para este provider.')

    def disponivel(self):
        return False
