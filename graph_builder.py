# from gevent import monkey
# monkey.patch_all()
# import gevent
# from gevent.pool import Pool

from typing import List, Iterable
from collections import defaultdict
import asyncio
import logging
from functools import wraps
from urllib.parse import urlparse
from async_dns.core import types
from async_dns.resolver import ProxyResolver
import networkx as nx
import httpx
import matplotlib.pyplot as plt
from neo3.network.node import NeoNode
from neo3.network.message import Message, MessageType
from neo3.network import payloads
from neo3 import settings
logger = logging.getLogger()


settings.network.magic = 877933390
settings.network.seedlist = [
                "seed1t4.neo.org:20333",
                "seed2t4.neo.org:20333",
                "seed3t4.neo.org:20333",
                "seed4t4.neo.org:20333",
                "seed5t4.neo.org:20333"
            ]
settings.network.standby_committee = [
              "023e9b32ea89b94d066e649b124fd50e396ee91369e8e2a6ae1b11c170d022256d",
              "03009b7540e10f2562e5fd8fac9eaec25166a58b26e412348ff5a86927bfac22a2",
              "02ba2c70f5996f357a43198705859fae2cfea13e1172962800772b3d588a9d4abd",
              "03408dcd416396f64783ac587ea1e1593c57d9fea880c8a6a1920e92a259477806",
              "02a7834be9b32e2981d157cb5bbd3acb42cfd11ea5c3b10224d7a44e98c5910f1b",
              "0214baf0ceea3a66f17e7e1e839ea25fd8bed6cd82e6bb6e68250189065f44ff01",
              "030205e9cefaea5a1dfc580af20c8d5aa2468bb0148f1a5e4605fc622c80e604ba",
              "025831cee3708e87d78211bec0d1bfee9f4c85ae784762f042e7f31c0d40c329b8",
              "02cf9dc6e85d581480d91e88e8cbeaa0c153a046e89ded08b4cefd851e1d7325b5",
              "03840415b0a0fcf066bcc3dc92d8349ebd33a6ab1402ef649bae00e5d9f5840828",
              "026328aae34f149853430f526ecaa9cf9c8d78a4ea82d08bdf63dd03c4d0693be6",
              "02c69a8d084ee7319cfecf5161ff257aa2d1f53e79bf6c6f164cff5d94675c38b3",
              "0207da870cedb777fceff948641021714ec815110ca111ccc7a54c168e065bda70",
              "035056669864feea401d8c31e447fb82dd29f342a9476cfd449584ce2a6165e4d7",
              "0370c75c54445565df62cfe2e76fbec4ba00d1298867972213530cae6d418da636",
              "03957af9e77282ae3263544b7b2458903624adc3f5dee303957cb6570524a5f254",
              "03d84d22b8753cf225d263a3a782a4e16ca72ef323cfde04977c74f14873ab1e4c",
              "02147c1b1d5728e1954958daff2f88ee2fa50a06890a8a9db3fa9e972b66ae559f",
              "03c609bea5a4825908027e4ab217e7efc06e311f19ecad9d417089f14927a173d5",
              "0231edee3978d46c335e851c76059166eb8878516f459e085c0dd092f0f1d51c21",
              "03184b018d6b2bc093e535519732b3fd3f7551c8cffaf4621dd5a0b89482ca66c9"
            ]
settings.network.validators_count = 7

loop = asyncio.get_event_loop()
# pool = Pool(10000)
failed_to_connect_to_nodes = set()
visited_nodes = set()
ip_location_dict = defaultdict(set)

client = httpx.AsyncClient()


httpx_usual_exceptions = (httpx.HTTPError, httpx.TimeoutException)
retry_lock = asyncio.Lock()


def async_retry(*exceptions, retries=5, cooldown=0):
    def wrap(func):
        @wraps(func)
        async def inner(*args, **kwargs):
            retries_count = retries
            while True:
                try:
                    result = await func(*args, **kwargs)
                except exceptions as err:
                    retries_count -= 1
                    if retries_count == 0:
                        # print(f'Too many retries')
                        raise err
                    else:
                        # print(f'Retry with remaining count {retries_count} before {cooldown} sec of cooldown')
                        time_before_acquire = loop.time()
                        await retry_lock.acquire()
                        time_after_acquire = loop.time()
                        await asyncio.sleep(max(cooldown - (time_after_acquire - time_before_acquire), 0))
                        retry_lock.release()
                else:
                    return result
        return inner
    return wrap


class Limiter:
    # domain -> req/sec:
    _limits = {
        'ip-api.com': 100,
    }
    # domain -> it's lock:
    _locks = defaultdict(asyncio.Lock)
    # domain -> it's last request time
    _times = defaultdict(lambda: 0)

    def __init__(self, url):
        self._host = urlparse(url).hostname

    async def __aenter__(self):
        await self._lock.acquire()
        to_wait = self._to_wait_before_request()
        # print(f'Wait {to_wait} sec before next request to {self._host}')
        await asyncio.sleep(to_wait)

    async def __aexit__(self, *args):
        # print(f'Request to {self._host} just finished')
        self._update_request_time()
        self._lock.release()

    @property
    def _lock(self):
        """Lock that prevents multiple requests to same host."""
        return self._locks[self._host]

    def _to_wait_before_request(self):
        """What time we need to wait before request to host."""
        request_time = self._times[self._host]
        request_delay = 1 / self._limits[self._host]
        now = asyncio.get_event_loop().time()
        to_wait = request_time + request_delay - now
        to_wait = max(0, to_wait)
        return to_wait

    def _update_request_time(self):
        now = loop.time()
        self._times[self._host] = now


class GraphBuilder:
    def __init__(self):
        self.graph = nx.Graph()
    
    def new_node_with_neighbours(self, node_ip: str, neighbour_ips: Iterable[str]):
        self.graph.add_node(node_ip)
        for neighbour_ip in neighbour_ips:
            self.graph.add_node(neighbour_ip)
            self.graph.add_edge(node_ip, neighbour_ip)
    
    def draw_graph(self, show_plot=False, with_node_name=True):
        graph = self.graph
        print(f'{graph.number_of_nodes()} nodes:')
        print(graph.nodes.data())
        print(f'{graph.number_of_edges()} edges:')
        print(graph.edges.data())

        if show_plot:
            d = dict(graph.degree)
            color_map = []
            for node in graph.nodes:
                if 'host' in graph.nodes._nodes[node]:
                    color_map.append('red')
                else:
                    color_map.append('skyblue')
            
            pos = nx.spring_layout(graph, seed=68)
            fig = plt.figure()
            timer = fig.canvas.new_timer(interval=10000)
            timer.add_callback(plt.close)
            nx.draw(graph, pos, with_labels=with_node_name, node_color=color_map, node_shape="o", linewidths=1,
                    font_size=2, font_color="black", edge_color="grey",
                    nodelist=d.keys(), node_size=[(v+5) * 5 for v in d.values()])
            plt.savefig('nodes.eps', bbox_inches='tight')
            timer.start()
            plt.show()


graph_builder = GraphBuilder()


async def get_addr(host_and_port: str) -> List[str]:
    host, port = host_and_port.split(':')
    get_ip_location_task = asyncio.create_task(get_ip_location(host))
    port = int(port)
    if port == 0:
        return []
    connected = False
    node = None
    try:
        node, error = await NeoNode.connect_to(host=host, port=port, timeout=10, loop=loop)
        if not node:
            raise Exception(error)
        connected = True
        node: NeoNode
        await node.send_message(Message(MessageType.GETADDR))
        for i in range(20):
            message = await node.read_message(timeout=5)
            if message.type == MessageType.ADDR:
                await node.disconnect(payloads.DisconnectReason.MAX_CONNECTIONS_REACHED)
                await get_ip_location_task
                return [address.address for address in message.payload.addresses]
    except:
        # print(f'Failed to connect to {host}:{port}')
        failed_to_connect_to_nodes.add(host_and_port)
        # logger.info(traceback.format_exc())
        if connected:
            await node.disconnect(payloads.DisconnectReason.MAX_CONNECTIONS_REACHED)
        await get_ip_location_task
        return []


async def build_topology(initial_ip_port: str):
    addresses = await get_addr(initial_ip_port)
    tasks = []
    for address in addresses:
        if address.endswith(':0') or address in visited_nodes:
            continue
        # print(address)
        tasks.append(asyncio.ensure_future(build_topology(address), loop=loop))
        visited_nodes.add(address)
    graph_builder.new_node_with_neighbours(
        initial_ip_port.split(":")[0], [address.split(':')[0] for address in addresses])
    if tasks:
        await asyncio.wait(tasks)


async def dns_resolve(host: str):
    """
    :param host: seed1t4.neo.org:20333 ; seed1t4.neo.org
    :return: ip_address:20333 ; ip_address
    """
    host_port_list = host.split(':')
    host = host_port_list[0]
    resolver = ProxyResolver(query_timeout=10)
    res, cached = await resolver.query(host, types.A)
    host_port_list[0] = res.an[0].data.data
    return ':'.join(host_port_list)


async def dns_resolve_many(hosts: List[str]):
    tasks, _ = await asyncio.wait([dns_resolve(host) for host in hosts])
    return [await task for task in tasks]


async def build_topology_from_many(initial_host_ports: List[str]):
    initial_ip_ports = await dns_resolve_many(initial_host_ports)
    for ip_port, host_port in zip(initial_ip_ports, initial_host_ports):
        ip, _ = ip_port.split(':')
        graph_builder.graph.add_node(ip, host=host_port)
    await asyncio.wait([asyncio.ensure_future(build_topology(address), loop=loop) for address in initial_ip_ports])
    await client.aclose()


@async_retry(*httpx_usual_exceptions, retries=-1, cooldown=60)
async def get_ip_location(ip: str):
    url = f'http://ip-api.com/json/{ip}'
    async with Limiter(url):
        r = await client.get(url)
    if r.status_code >= 400:
        r.raise_for_status()
    try:
        r_dict = r.json()
        key = f'{r_dict["country"]} {r_dict["city"]}'
        ip_location_dict[key].add(ip)
    except:
        pass


loop.run_until_complete(build_topology_from_many(settings.network.seedlist))
# loop.run_until_complete(asyncio.sleep(60))
# loop.stop()
print(f'Failed to connect to {len(failed_to_connect_to_nodes)} nodes:')
print(failed_to_connect_to_nodes)
print('ip_location_dict:')
print(ip_location_dict)
graph_builder.draw_graph(show_plot=False)
