"""python -m unittest discover -s tests -v"""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import interaction_logger
from observability import request_context, medir, evento, last_error_stage

class ObservabilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch_base = patch.object(interaction_logger, 'BASE', Path(self.tmp.name))
        self.patch_base.start()
        self.addCleanup(self.patch_base.stop)
        self.addCleanup(self.tmp.cleanup)

    def entries(self):
        return [json.loads(line) for file in Path(self.tmp.name).glob('*.jsonl')
                for line in file.read_text(encoding='utf8').splitlines()]

    def test_success_and_sensitive_data_not_logged(self):
        with request_context('s1','i1'):
            with medir('redshift_query',details={'row_count': 6, 'secret': 'should never appear'}):
                pass
        events = self.entries()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['stage'], 'redshift_query')
        self.assertEqual(events[0]['details'], {'row_count': 6})
        self.assertNotIn('secret', str(events))

    def test_error_stage_survives_exception_and_reset(self):
        with request_context('s1','i1'):
            with self.assertRaisesRegex(ValueError,'failure'):
                with medir('llm_parse'):
                    raise ValueError('failure')
            self.assertEqual(last_error_stage(), 'llm_parse')
        self.assertIsNone(last_error_stage())
        ev = self.entries()[0]
        self.assertEqual(ev['status'], 'error')
        self.assertEqual(ev['error_type'], 'ValueError')
        self.assertNotIn('failure',str(ev))

    def test_nested_error_keeps_inner_stage(self):
        with request_context("s", "i"):
            with self.assertRaises(ValueError):
                with medir("query_engine"):
                    with medir("redshift_query"):
                        raise ValueError("hidden")
            self.assertEqual(last_error_stage(), "redshift_query")

    def test_no_interaction_no_event(self):
        with medir('redshift_query'):
            pass
        self.assertEqual(self.entries(), [])

    def test_parallel_contexts_are_isolated(self):
        def run(i):
            with request_context('s'+str(i), 'i'+str(i)):
                with medir('planner_mode'):
                    pass
        threads=[threading.Thread(target=run,args=(i,)) for i in range(12)]
        for t in threads:t.start()
        for t in threads:t.join()
        self.assertEqual({e['interaction_id'] for e in self.entries()}, {'i'+str(i) for i in range(12)})

    def test_event_filter_and_backward_compatibility(self):
        with request_context('session','interaction'):
            evento('planner_outcome',details={'planner_decision':'clarify','reason_code':'ambiguous_scope', 'prompt':'secret'})
        self.assertNotIn('secret',str(self.entries()))
        self.assertEqual(self.entries()[0]['details']['planner_decision'],'clarify')

if __name__ == '__main__':unittest.main()
