"""Brownfield config-discovery package.

Walks a live BIG-IP via iControl REST and emits AS3/DO declarations plus
Terraform import blocks pointing at existing F5Networks/bigip provider
resources. See docs/decisions/007-brownfield-config-discovery.md for the
scope, prior-art rationale, and apply-no-op adoption flow for bigip_do.

Phase 5 PR-1 ships the extraction layer (this checkpoint) and the
emission + Terraform import + CLI layer in following checkpoints.
"""
