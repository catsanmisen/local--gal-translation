"""Shared launcher/control CLI configuration; explicit flags take precedence."""
import argparse
import os


def client_port(value):
    try:
        port = int(value)
    except (TypeError, ValueError):
        raise argparse.ArgumentTypeError('端口必须是 1–65535 的整数。')
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError('端口必须是 1–65535 的整数。')
    return port


def add_client_port(parser):
    parser.add_argument('--port', type=client_port, default=os.environ.get('GALTRANSL_CLIENT_PORT') or '18039',
        help='本机客户端端口；默认读取 GALTRANSL_CLIENT_PORT，否则使用 18039')
