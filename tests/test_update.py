import json, tempfile, unittest
from pathlib import Path
import update_feed

class RadarTests(unittest.TestCase):
    def setUp(self): self.cfg=json.loads((Path(__file__).parents[1]/"config.json").read_text())
    def test_relevance(self):
        item={"title":"Human milk metabolomics in preterm infants","description":"lactation microbiome","agency":"NICHD","number":"RFA-HD-27-001"}
        self.assertGreaterEqual(update_feed.score_item(item,self.cfg)["score"],8)
    def test_exclusion(self):
        item={"title":"SBIR small business lactation device","description":"","agency":"","number":""}
        self.assertLess(update_feed.score_item(item,self.cfg)["score"],self.cfg["minimum_score"])
    def test_demo_render(self):
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/"index.html"; update_feed.render([update_feed.score_item(update_feed.demo_items()[0],self.cfg)],self.cfg,out,[])
            self.assertIn("Johnson Lab NIH Funding Radar",out.read_text())

if __name__=="__main__": unittest.main()

