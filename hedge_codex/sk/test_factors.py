import copy
import unittest
from datetime import date,timedelta
from analyze_factors import basic_features,labels,corr,pairs,summary


def sample(n=40):
    rows=[]
    for i in range(n):
        c=100+i+(i%3)*.2
        rows.append([(date(2026,1,1)+timedelta(days=i)).isoformat(),c,c+1,c-1,c,100+i*10])
    return rows


class FactorTests(unittest.TestCase):
    def test_relative_volume_excludes_today_from_denominator(self):
        s=sample();s[5][5]=1000
        self.assertAlmostEqual(basic_features(s)[s[5][0]]['rvol5'],1000/120)

    def test_labels_start_next_session_not_same_session(self):
        s=sample();before=labels(s)
        s[0][2]=99999;s[0][3]=.01
        after=labels(s)
        self.assertEqual(before[s[0][0]],after[s[0][0]])

    def test_future_changes_cannot_change_earlier_features(self):
        s=sample();a=basic_features(s);e=copy.deepcopy(s)
        e[20][4]=800;e[20][5]=900000
        b=basic_features(e)
        for row in s[:20]:self.assertEqual(a[row[0]],b[row[0]])

    def test_forward_label_has_exact_horizon(self):
        s=sample();t=labels(s)
        self.assertEqual(t[s[0][0]]['end5'],s[5][0])
        self.assertNotIn('rv5',t[s[-5][0]])
        self.assertIn('rv5',t[s[-6][0]])

    def test_equal_forward_close_but_high_path_volatility(self):
        s=sample(6)
        for i,c in enumerate([100,120,80,120,80,100]):s[i][1:5]=[c,c,c,c]
        t=labels(s)[s[0][0]]
        self.assertEqual(t['endpoint5'],0)
        self.assertGreater(t['rv5'],50)

    def test_rank_correlation_handles_ties_and_constant_series(self):
        self.assertAlmostEqual(corr([1,1,2,3],[3,3,2,1]),-1)
        self.assertIsNone(corr([1,1,1,1],[1,2,3,4]))

    def test_training_does_not_consume_labels_crossing_boundary(self):
        s=sample();f=basic_features(s);t=labels(s);boundary=s[24][0]
        r=summary(f,t,'rvol5',boundary)
        expected=[p for p in pairs(f,t,'rvol5')if p['end']<=boundary]
        self.assertEqual(r['train_n'],len(expected))
        self.assertTrue(all(p['date']<boundary for p in expected))


if __name__=='__main__':unittest.main()
