"""Regression: integrate monthly totals without inventing missing components."""
import unittest
from unittest.mock import patch
import update_pipeline as pipeline

class MonthlyIntegrationTest(unittest.TestCase):
    def test_month_is_saved(self):
        data = {'systemMonthly2026':[{'month':'2026-07','imports':'8,94','exports':'6,67'}],
                'systemMonthlyMeta':{'latest':'2026-07'},'systemKpis':[],
                'updates':[{'name':'Flujos mensuales'}]}
        def parsed(month):
            return {'imports':8.94,'exports':6.67} if month=='2026-07' else {'imports':9.10,'exports':6.80}
        with patch.object(pipeline,'fetch',return_value=b'Agosto 2026 Julio 2026'), patch.object(pipeline,'_read_monthly_flows_pdf',side_effect=parsed):
            pipeline.monthly_flows_status(data)
        self.assertEqual(data['systemMonthlyMeta']['latest'],'2026-08')
        self.assertEqual(data['systemMonthly2026'][-1]['imports'],'9,10')
        self.assertNotIn('lng',data['systemMonthly2026'][-1])
        self.assertEqual(data['updates'][0]['status'],'new_report')

if __name__=='__main__':
    unittest.main()
