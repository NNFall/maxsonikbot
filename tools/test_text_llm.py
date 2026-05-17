from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_config
from services.dream_ai import generate_dream_interpretation_text


async def _run(dream: str, mode: str) -> None:
    load_config()
    text = await generate_dream_interpretation_text(dream, mode=mode)
    print('\n----- MODEL OUTPUT START -----\n')
    print(text)
    print('\n----- MODEL OUTPUT END -----')


def main() -> None:
    parser = argparse.ArgumentParser(description='Test text LLM chain for dream interpretation')
    parser.add_argument('--dream', default='Мне приснилось, что я иду по темному дому и ищу открытую дверь.')
    parser.add_argument('--mode', choices=['teaser', 'full'], default='teaser')
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format='%(asctime)s | %(levelname)s | %(name)s | %(message)s')
    asyncio.run(_run(args.dream, args.mode))


if __name__ == '__main__':
    main()
