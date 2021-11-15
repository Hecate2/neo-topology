from typing import Iterable
import networkx as nx
import matplotlib.pyplot as plt

class GraphBuilder:
    def __init__(self):
        self.graph = nx.Graph()
    
    def new_node_with_neighbours(self, node_ip: str, neighbour_ips: Iterable[str]):
        if node_ip not in self.graph:
            self.graph.add_node(node_ip)
        for neighbour_ip in neighbour_ips:
            self.graph.add_edge(node_ip, neighbour_ip)

    def draw_graph(self):
        nx.draw(self.graph)
        plt.show()