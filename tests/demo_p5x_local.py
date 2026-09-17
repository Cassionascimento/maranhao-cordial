"""Demonstração local reproduzível. Não importa main nem conecta banco/LLM.
Execute PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:. python3 tests/demo_p5x_local.py.
Os artefatos ficam em /tmp/p5x-demo-local; nada é inserido em produção.
"""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch
import mi_secretario_executivo as secretary
import mi_presentation_engine as presentation
import mi_chart_engine as chart
import mi_label_studio as label
from mi_image_provider import MockImageProvider
from tests.test_mi_pirret_criativo import _cliente_mock
from tests.test_p5x_end_to_end import Conn
from tests.test_mi_artefatos import _db_vazio


def demonstrar():
    dest=Path('/tmp/p5x-demo-local');dest.mkdir(exist_ok=True)
    sha=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip()
    commits=int(subprocess.check_output(['git','rev-list','--count','main..HEAD'],text=True))
    spec={'chart_type':'bar','title':'Dado técnico real — commits sobre main',
        'x':['Commits da branch'],'series':[{'name':'Commits','values':[commits]}],
        'source':f'git rev-list main..HEAD · {sha[:12]}','freshness':'checkout local',
        'units':'commits; não são vendas','confidence':'REAL'}
    db=_db_vazio();factory=lambda:Conn(db)
    with patch('socket.socket.connect',side_effect=AssertionError('rede proibida')):
        with patch.object(secretary,'OpenAI',side_effect=RuntimeError('provider desabilitado')):
            ata=secretary.montar_ata_executiva({'id':'demo-local','demanda':'DEMONSTRAÇÃO LOCAL — NÃO É REUNIÃO REAL',
                'conclusao':'Dados comerciais não consultados. AGUARDANDO DADOS.', 'participantes':[],
                'dados_apresentados':{},'recomendacoes':[]})
        pptx=presentation.montar_deck_executivo(ata,[spec,chart.NOT_ENOUGH_DATA])
        dest.joinpath('demonstracao-local.pptx').write_bytes(pptx)
        dest.joinpath('historico-tecnico-real.svg').write_text(chart.renderizar_svg(spec))
        result=label.gerar_conceito_rotulo(factory,'SYNTHETIC_TEST — pipeline de rótulo','SKU-TEST',
            brand_context={'referencias_aprovadas':[]},quantidade=1,provider=MockImageProvider(),cliente=_cliente_mock())
        row=db['artefatos'][result['artefatos'][0]['id']]
        dest.joinpath('manifesto.json').write_text(json.dumps({'sha':sha,'grafico':spec,
            'pptx':'arquivo real; reunião simulada; não representa resultado comercial',
            'pirret':'SYNTHETIC_TEST — mock 1x1, não comprova qualidade visual',
            'metadata_pirret':row['metadata'],'envios':0},ensure_ascii=False,indent=2))
    print(dest)

if __name__=='__main__':demonstrar()
