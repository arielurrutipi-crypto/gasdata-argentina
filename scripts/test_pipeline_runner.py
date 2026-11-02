import json
from pathlib import Path
import tempfile
import time
import unittest
from pipeline_runner import PipelineRunner


class RunnerTests(unittest.TestCase):
    def test_timeout_discards_unconfirmed_changes_and_continues(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'data.json'
            data = dict(value='confirmed', regulations=[dict(publishedAt=None)])
            runner = PipelineRunner(data, path, lambda:'now')
            def stuck(d):
                d['value'] = 'incomplete'
                time.sleep(5)
            self.assertEqual(runner.run('slow', stuck, timeout=.05), 'timeout')
            self.assertEqual(data['value'], 'confirmed')
            runner.run('news', lambda d:d.update(news=['fresh']))
            saved = json.loads(path.read_text())
            self.assertEqual(saved['news'], ['fresh'])
            self.assertEqual(saved['value'], 'confirmed')
            self.assertIsNone(saved['regulations'][0]['publishedAt'])

    def test_exception_keeps_previous_success_and_records_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            data = dict(value=2)
            runner = PipelineRunner(data, Path(folder)/'data.json', lambda:'now')
            runner.run('source', lambda d:d.update(value=3))
            def fail(d):
                d['value'] = 99
                raise ValueError('bad source')
            self.assertEqual(runner.run('source', fail), 'error')
            self.assertEqual(data['value'], 3)
            self.assertEqual(data['pipelineStages']['source']['completedAt'], 'now')

    def test_cycle_budget_defers_without_calling_source(self):
        with tempfile.TemporaryDirectory() as folder:
            data = dict(value=1)
            runner = PipelineRunner(data, Path(folder)/'data.json', lambda:'now', budget=0)
            self.assertEqual(runner.run('source', lambda d:d.update(value=9)), 'deferred')
            self.assertEqual(data['value'], 1)


class PipelineIntegration(unittest.TestCase):
    def test_regulation_backlog_is_preserved_and_drained(self):
        import update_pipeline as pipeline
        from unittest.mock import patch
        entries={str(i):dict(url=str(i),day=pipeline.now().date(),label=f'Resolución {i}/2026') for i in range(13)}
        data={'regulations':[]}
        with patch.object(pipeline,'_scan_bora_dates',return_value=(entries,1,[])), patch.object(pipeline,'_parse_bora_detail',return_value=None) as reader:
            pipeline.update_regulations(data)
            self.assertEqual(reader.call_count,12)
        self.assertEqual(len(data['regulationScan']['pendingDetails']),1)
        self.assertFalse(data['regulationScan']['complete'])
        with patch.object(pipeline,'_scan_bora_dates',return_value=({},1,[])), patch.object(pipeline,'_parse_bora_detail',return_value=None) as reader:
            pipeline.update_regulations(data)
            self.assertEqual(reader.call_count,1)
        self.assertEqual(data['regulationScan']['pendingDetails'],[])
        self.assertTrue(data['regulationScan']['complete'])

    def test_market_reader_updates_without_waiting_for_other_sources(self):
        import automatic_sources as market
        from unittest.mock import Mock, patch
        from datetime import datetime
        data={'marketPrices':[{'id':'wb_europe','value':'old','observationDate':'2026-09'}]}
        fetch=Mock(return_value=b'workbook')
        with patch.object(market,'eia_latest',return_value=(datetime(2026,10,30),3.5)):
            market.update_market(data,fetch,lambda:'now',only='henry_hub')
        self.assertEqual(fetch.call_count,1)
        prices={row['id']:row for row in data['marketPrices']}
        self.assertEqual(prices['henry_hub']['value'],'3,50')
        self.assertEqual(prices['wb_europe']['value'],'old')
        self.assertNotIn('validatedAt',prices['wb_europe'])
        self.assertEqual(data['marketAutomation']['readers'],{'henry_hub':'ok'})

    def test_main_completes_all_stages_offline(self):
        import update_pipeline as pipeline
        import automatic_sources
        import news_translation
        from unittest.mock import patch
        from contextlib import ExitStack
        names = ['sync_update_catalog', 'update_news', 'update_infrastructure', 'update_layers',
                 'update_bagsa_news', 'update_resolution_export', 'update_regulations',
                 'sync_regulator_catalogue', 'sync_tariffs_from_regulations', 'sync_tariffs_from_enargas',
                 'sync_enargas_tariff_series', 'sync_tariff_archive', 'update_tariff_comparison',
                 'validate_pages', 'production', 'update_basin_production', 'demand_priority',
                 'system_market', 'monthly_flows_status', 'transport_capacity', 'refresh_source_status']
        def callback(name):
            def run(data, *args, **kwargs): data.setdefault('called', []).append(name)
            return run
        with tempfile.TemporaryDirectory() as folder, ExitStack() as stack:
            path=Path(folder)/'data.json'; path.write_text('{"meta": {}}')
            stack.enter_context(patch.object(pipeline, 'DATA', path))
            for name in names: stack.enter_context(patch.object(pipeline, name, callback(name)))
            stack.enter_context(patch.object(automatic_sources, 'update_market', callback('market')))
            stack.enter_context(patch.object(automatic_sources, 'update_bopba', callback('pba')))
            stack.enter_context(patch.object(news_translation, 'translate_news', callback('translation')))
            pipeline.main()
            saved=json.loads(path.read_text())
            self.assertIn('update_basin_production', saved['called'])
            self.assertIn('pba', saved['called'])
            self.assertTrue(all(s['status']=='completed' for s in saved['pipelineStages'].values()))

if __name__ == '__main__': unittest.main()
