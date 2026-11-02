"""Bound collection stages and checkpoint completed data before the next source."""
import json
import multiprocessing
from pathlib import Path
import tempfile
import time
import traceback


def atomic_json(path, value):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def _collect(callback, data, result):
    try:
        callback(data)
        atomic_json(result, dict(ok=True, data=data))
    except Exception:
        print(traceback.format_exc(), flush=True)
        atomic_json(result, dict(ok=False, error='La consulta falló; se conserva el último dato confirmado y se reintentará'))


class PipelineRunner:
    def __init__(self, data, path, timestamp, budget=1200):
        self.data, self.path, self.timestamp = data, Path(path), timestamp
        self.deadline = time.monotonic() + budget

    def run(self, name, callback, timeout=90):
        start = time.monotonic()
        allowed = min(timeout, max(0, self.deadline - start))
        print(f'STAGE START {name} budget={allowed:.0f}s', flush=True)
        state = dict(self.data.get('pipelineStages', {}).get(name, {}))
        state.update(attemptedAt=self.timestamp())
        if allowed <= 0:
            state.update(status='deferred', error='Presupuesto del ciclo agotado; se reintentará en el próximo ciclo')
        else:
            with tempfile.TemporaryDirectory(prefix='gasdata-stage-') as folder:
                result = Path(folder) / 'result.json'
                worker = multiprocessing.get_context('fork').Process(target=_collect, args=(callback, self.data, result))
                worker.start()
                worker.join(allowed)
                if worker.is_alive():
                    worker.terminate()
                    worker.join(3)
                    if worker.is_alive():
                        worker.kill()
                        worker.join()
                    state.update(status='timeout', error=f'La etapa superó {allowed:.0f} s; se conserva el último dato confirmado')
                elif result.exists():
                    outcome = json.loads(result.read_text(encoding='utf-8'))
                    if outcome['ok']:
                        self.data.clear()
                        self.data.update(outcome['data'])
                        state.update(status='completed', error=None, completedAt=self.timestamp())
                    else:
                        state.update(status='error', error=outcome['error'])
                else:
                    state.update(status='error', error=f'La etapa terminó sin resultado (código {worker.exitcode})')
        state['durationSeconds'] = round(time.monotonic() - start, 2)
        self.data.setdefault('pipelineStages', {})[name] = state
        self.data.setdefault('meta', {})['updatedAt'] = self.timestamp()
        atomic_json(self.path, self.data)
        print(f'STAGE END {name} {state["status"]} {state["durationSeconds"]}s', flush=True)
        return state['status']
