import copy
import unittest

from odds_analyzer.learning import freeze_predictions, merge_learning_archives
from odds_analyzer.jobs.review_results import review_checker_results
from test_learning import match


class MismatchOnlyTests(unittest.TestCase):
    def test_new_archives_only_record_mismatches_and_keep_existing_data(self):
        ordinary = match()
        mismatch = match(2)
        mismatch['mismatch'] = {'matched': True}
        payload = {'learning_evaluation': {'legacy': True}, 'model_reviews': [{'legacy': True}]}
        freeze_predictions(payload, [ordinary], '2026-06-30T12:00:00+08:00')
        before = copy.deepcopy(payload)
        freeze_predictions(payload, [ordinary, mismatch], '2026-06-30T13:00:00+08:00', mismatch_only=True)
        self.assertEqual(payload['prediction_archive'][:-1], before['prediction_archive'])
        self.assertEqual(payload['prediction_archive'][-1]['match'], mismatch)
        self.assertEqual(payload['learning_evaluation'], before['learning_evaluation'])
        self.assertEqual(payload['model_reviews'], before['model_reviews'])

    def test_legacy_non_mismatch_checker_is_preserved_without_review(self):
        ordinary = match()
        payload = {'checker_history': [ordinary], 'strategy_performance': {'legacy': True},
                   'learning_evaluation': {'legacy': True}, 'model_reviews': []}
        original = copy.deepcopy(payload)
        updated, counts = review_checker_results(payload, ordinary['batch_date'], (), '2026-07-02T08:00:00+08:00')
        self.assertEqual(payload, original)
        for key in original:
            self.assertEqual(updated[key], original[key])
        self.assertEqual(sum(counts.values()), 0)

    def test_publish_merge_does_not_recalculate_legacy_statistics(self):
        payload = {'learning_evaluation': {'legacy': True}, 'model_evaluation': {'legacy': True}}
        merged = merge_learning_archives(payload, {})
        for key in payload:
            self.assertEqual(merged[key], payload[key])
