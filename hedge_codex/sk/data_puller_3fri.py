#!/usr/bin/env python3
"""Compatibility entry point for full verified SKHY stock/put refresh.
The new refresh replaces incremental ATM-only caching. Use --help for options.
"""
from refresh_data import main
if __name__ == '__main__':
    main()
