"""Allow running NOVA as a module: python -m nova"""
import asyncio
from nova.app import main

if __name__ == "__main__":
    main()
