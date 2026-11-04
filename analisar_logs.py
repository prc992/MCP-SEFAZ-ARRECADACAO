"""Análise offline dos JSONL Faro (v1 e v2), sem dependências extras.

Uso: python analisar_logs.py --input ./logs_interacoes --output ./relatorio_logs
Não envia dados a serviços externos. O CSV de priorização contém perguntas
potencialmente sensíveis: compartilhe apenas com equipe autorizada.
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import math
import statistics
from pathlib import Path


def carregar(entrada):
    p = Path(entrada)
    paths = sorted(p.glob('interacoes_*.jsonl')) if p.is_dir() else [p]
    rows, invalid = [], 0
    for path in paths:
        with path.open(encoding='utf-8-sig') as file:
            for line in file:
                if not line.strip():
                    continue
                try:
                    item = json.loads(line)
                    if isinstance(item, dict):
                        item['_file'] = path.name
                        rows.append(item)
                    else:
                        invalid += 1
                except (ValueError, UnicodeDecodeError):
                    invalid += 1
    return rows, invalid


def pct(n, total):
    return round(100 * n / total, 1) if total else None


def percentil(values, p):
    s = sorted(float(x) for x in values if isinstance(x, (float, int)))
    if not s:
        return None
    at = (len(s) - 1) * p
    lo, hi = math.floor(at), math.ceil(at)
    return round(s[lo] + (s[hi] - s[lo]) * (at - lo), 1)


def categoria(item):
    explicit = item.get('question_category')
    if explicit:
        return explicit
    spec = item.get('query_spec') or {}
    if spec.get('report_type') == 'icms_fecop':
        return 'demonstrativo_icms_fecop'
    if spec.get('analysis_type') == 'compare_periods':
        return 'comparacao_periodos'
    if spec.get('analysis_type') == 'time_series':
        return 'serie_temporal'
    if spec.get('group_by') == 'decendio':
        return 'decendios'
    if spec.get('group_by') == 'segmento':
        return 'segmentos'
    if spec.get('group_by') in ('receita', 'codigo_receita', 'subgrupo'):
        return 'receitas'
    return 'nao_classificada'


def signature(item):
    if item.get('question_signature'):
        return item['question_signature']
    spec = item.get('query_spec') or {}
    # V1 não tem assinatura; agrupar pelo texto exato, sem falsa equivalência semântica.
    import hashlib
    base = str(item.get('question') or '').strip().lower()
    return hashlib.sha256(base.encode()).hexdigest()[:16]


def analisar(eventos, invalid):
    its = [x for x in eventos if x.get('event_type') == 'interaction']
    ids = {(i.get('session_id'), i.get('interaction_id')): i for i in its}
    latest_feedback = {}
    for e in eventos:
        if e.get('event_type') == 'feedback':
            key = (e.get('session_id'), e.get('interaction_id'))
            latest_feedback[key] = e.get('vote')
    for key, voto in latest_feedback.items():
        if key in ids:
            ids[key]['_latest_vote'] = voto
    stages = [x for x in eventos if x.get('event_type') == 'stage']
    times = [i.get('duration_ms') for i in its if isinstance(i.get('duration_ms'), (int, float))]
    erros = [i for i in its if i.get('status') == 'error']
    lentas = [i for i in its if isinstance(i.get('duration_ms'), (int, float)) and i['duration_ms'] >= 10000]
    grupos = collections.defaultdict(list)
    for i in its:
        grupos[signature(i)].append(i)
    ranking = []
    for chave, items in grupos.items():
        failures = sum(x.get('status') == 'error' for x in items)
        negatives = sum(x.get('_latest_vote') == 'negative' for x in items)
        positives = sum(x.get('_latest_vote') == 'positive' for x in items)
        slow = sum(isinstance(x.get('duration_ms'), (float, int)) and x['duration_ms'] >= 10000 for x in items)
        weight = 3 * failures + 2 * negatives + slow + len(items)
        ranking.append({'signature': chave, 'category': categoria(items[0]),
                        'example_question': items[0].get('question') or '',
                        'requests': len(items), 'errors': failures, 'negative_votes': negatives,
                        'positive_votes': positives, 'slow_requests': slow,
                        'p95_ms': percentil([x.get('duration_ms') for x in items], .95),
                        'priority_score_heuristic': weight})
    ranking.sort(key=lambda x: (-x['priority_score_heuristic'], -x['requests']))
    por_etapa = {}
    for etapa in sorted({s.get('stage') for s in stages if s.get('stage')}):
        vals = [s.get('duration_ms') for s in stages if s.get('stage') == etapa]
        por_etapa[etapa] = {'count': len(vals), 'p50_ms': percentil(vals, .5),
                            'p95_ms': percentil(vals, .95),
                            'errors': sum(s.get('status') == 'error' for s in stages if s.get('stage') == etapa)}
    summary = {'schema_versions': dict(collections.Counter(str(i.get('schema_version', 1)) for i in its)),
               'event_count': len(eventos), 'invalid_json_lines': invalid,
               'interactions': len(its), 'sessions': len(set(x.get('session_id') for x in its)),
               'errors': len(erros), 'error_rate_pct': pct(len(erros), len(its)),
               'slow_over_10s': len(lentas), 'slow_rate_pct': pct(len(lentas), len(its)),
               'duration_p50_ms': percentil(times, .5), 'duration_p95_ms': percentil(times, .95),
               'categories': dict(collections.Counter(categoria(x) for x in its)),
               'actions': dict(collections.Counter(x.get('action') or 'sem_acao' for x in its)),
               'answer_sources': dict(collections.Counter(x.get('answer_source') or 'desconhecida' for x in its)),
               'error_types': dict(collections.Counter(x.get('error_type') or 'nao_classificado' for x in erros)),
               'feedback_votes_latest': dict(collections.Counter(latest_feedback.values())),
               'stage_timings': por_etapa,
               'stage_coverage_pct': pct(len({(s.get('session_id'), s.get('interaction_id')) for s in stages}), len(its)),
               'note': 'success = sem exceção reportada, NÃO significa resposta correta. Scores são heurísticos.'}
    return summary, ranking


def gravar(out, summary, ranking):
    out = Path(out)
    out.mkdir(exist_ok=True, parents=True)
    (out / 'resumo.json').write_text(json.dumps(summary, indent=2, ensure_ascii=False), encoding='utf-8')
    with (out / 'prioridades.csv').open('w', encoding='utf-8-sig', newline='') as f:
        cols = ['signature','category','example_question','requests','errors','negative_votes',
                'positive_votes','slow_requests','p95_ms','priority_score_heuristic']
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        writer.writerows(ranking)
    (out / 'LEIA-ME.txt').write_text(
        'Prioridades são heurísticas, não avaliação de acurácia.\n'
        'Analise manualmente amostra de perguntas de cada categoria.\n'
        'Perguntas e IDs podem ser sensíveis; restrinja acesso aos relatórios.\n', encoding='utf-8')


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True, help='Pasta de JSONL ou arquivo JSONL')
    p.add_argument('--output', default='relatorio_logs')
    args = p.parse_args()
    ev, invalid = carregar(args.input)
    summary, ranking = analisar(ev, invalid)
    gravar(args.output, summary, ranking)
    print(json.dumps({'interactions': summary['interactions'], 'errors': summary['errors'],
                      'p95_ms': summary['duration_p95_ms'], 'questions_groups': len(ranking),
                      'output': args.output}, ensure_ascii=False))


if __name__ == '__main__':
    main()
