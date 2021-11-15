# from gevent import monkey
# monkey.patch_all()
# import gevent
# from gevent.pool import Pool

from typing import List
import asyncio
import logging
import traceback
from neo3.network.node import NeoNode
from neo3.network.message import Message, MessageType
from neo3.network import payloads
from neo3 import settings
from graph import GraphBuilder
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


async def get_addr(host: str, port: int) -> List[str]:
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
                return [address.address for address in message.payload.addresses]
    except:
        print(f'Failed to connect to {host}:{port}')
        # logger.info(traceback.format_exc())
        if connected:
            await node.disconnect(payloads.DisconnectReason.MAX_CONNECTIONS_REACHED)
        return []


g = GraphBuilder()
# pool = Pool(10000)


async def build_topology(initial_address: str = 'seed1t4.neo.org', initial_port: int = 20333):
    addresses = await get_addr(initial_address, initial_port)
    g.new_node_with_neighbours(f'{initial_address}:{initial_port}', addresses)
    for address in addresses:
        ip, port = address.split(':')
        port = int(port)
        if port == 0:
            continue
        # print(address)
        asyncio.ensure_future(build_topology(ip, port))

asyncio.ensure_future(build_topology())
loop.run_until_complete(asyncio.sleep(60))
loop.stop()
g.draw_graph()