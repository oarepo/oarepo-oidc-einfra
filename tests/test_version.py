# SPDX-FileCopyrightText: 2024 CESNET z.s.p.o
# SPDX-License-Identifier: MIT

"""Tests for version."""

from __future__ import annotations


def test_version():
    from oarepo_oidc_einfra import __version__

    assert __version__ is not None
