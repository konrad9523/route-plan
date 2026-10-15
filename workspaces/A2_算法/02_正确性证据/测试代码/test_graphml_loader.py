import tempfile
import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "01_实现清单"))
from graphml_to_graph import load_graphml


class GraphMLLoaderTests(unittest.TestCase):
    def test_loads_directed_edges_coordinates_and_line_geometry(self):
        graphml = '''<?xml version="1.0" encoding="UTF-8"?>
        <graphml xmlns="http://graphml.graphdrawing.org/xmlns">
          <key id="x" for="node" attr.name="x" attr.type="double"/>
          <key id="y" for="node" attr.name="y" attr.type="double"/>
          <key id="length" for="edge" attr.name="length" attr.type="double"/>
          <key id="geometry" for="edge" attr.name="geometry" attr.type="string"/>
          <graph edgedefault="directed">
            <node id="a"><data key="x">-77.0</data><data key="y">38.0</data></node>
            <node id="b"><data key="x">-76.9</data><data key="y">38.1</data></node>
            <edge id="road-1" source="a" target="b">
              <data key="length">123.5</data>
              <data key="geometry">LINESTRING (-77.0 38.0, -76.95 38.05, -76.9 38.1)</data>
            </edge>
          </graph>
        </graphml>'''
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "tiny.graphml"
            path.write_text(graphml, encoding="utf-8")
            graph, positions, geometries = load_graphml(path)

        self.assertEqual(graph["a"], [("b", 123.5, "road-1")])
        self.assertEqual(graph["b"], [])
        self.assertEqual(positions["a"], (-77.0, 38.0))
        self.assertEqual(geometries["road-1"], [(-77.0, 38.0), (-76.95, 38.05), (-76.9, 38.1)])

    def test_rejects_undirected_graphml(self):
        graphml = '''<graphml><graph edgedefault="undirected"/></graphml>'''
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "undirected.graphml"
            path.write_text(graphml, encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "directed"):
                load_graphml(path)


if __name__ == "__main__":
    unittest.main()
