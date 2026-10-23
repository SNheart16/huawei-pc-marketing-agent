"""Read-only retrieval from an external local knowledge-base directory.

Nothing is copied, indexed on disk, downloaded, or written to the source tree.
All source references returned to callers are relative to LOCAL_KB_PATH.
"""

import os
import re
import stat
from pathlib import Path
from typing import Optional
from urllib.parse import unquote, urlsplit


class LocalKbClient:
    """Read a local snapshot without treating nearby files as model evidence."""

    _TEXT = {".md", ".markdown", ".txt"}
    _IMAGES = {".jpg", ".jpeg", ".png", ".webp"}
    _MAX_TEXT_BYTES = 4 * 1024 * 1024

    def __init__(self, kb_path: Optional[Path] = None) -> None:
        configured = kb_path if kb_path is not None else os.environ.get("LOCAL_KB_PATH")
        self._configured_path = Path(configured) if configured and str(configured).strip() else None

    def retrieve_product_documents(
        self,
        product_query: str,
        kb_name: str = "任德耀新建华为PC知识库",
    ) -> dict:
        """Return separate exact-model documents and conservative image matches.

        A body-only mention in an index or a document with a generic title does
        not establish product identity. Ambiguous query results expose candidate
        identities, but do not combine their contents into selected facts.
        """
        if not isinstance(product_query, str) or not product_query.strip():
            raise ValueError("product_query must be a non-empty str")
        if not isinstance(kb_name, str) or not kb_name.strip():
            raise ValueError("kb_name must be a non-empty str")
        query = product_query.strip()
        result = {
            "status": "needs_input", "query": query,
            "selected_product_model": None, "candidate_models": [],
            "documents": [], "media": [], "warnings": [],
            "missing_information": [],
            "image_counts": {"confirmed": 0, "unknown": 0},
            "knowledge_source": {
                "mode": "local", "name": kb_name, "live": False,
                "status": "ok",
                "message": "使用本地只读副本；资料及价格的时效性需另行核验。",
            },
        }
        warnings = result["warnings"]
        root = self._root()
        if root is None:
            result["status"] = "partial"
            result["knowledge_source"]["status"] = "unavailable"
            result["knowledge_source"]["message"] = "本地知识库配置缺失或目录不可安全读取。"
            result["missing_information"].append("LOCAL_KB_PATH 未配置，或配置目录不可读取。")
            return result

        text_files, image_files = self._scan(root, warnings)
        family = self._family(query)
        ambiguous_query = self._model_key(query) == self._model_key(family)
        records = []
        candidates = {}
        excluded = 0
        for path in text_files:
            relative = path.relative_to(root).as_posix()
            content = self._read_text(root, path, warnings)
            if content is None:
                continue
            first_title = next(iter(re.findall(r"(?m)^#\s+(.+)$", content)), "")
            identity_headings = re.findall(r"(?m)^#{1,6}\s+(.+)$", content)
            identity_fields = re.findall(
                r"(?mi)^\s*(?:[-*]\s*)?(?:product_name|product_model|产品名称|产品型号|完整型号)"
                r"\s*[:：]\s*([^\r\n]+)", content,
            )
            identity_sources = [path.stem, *identity_headings, *identity_fields]
            related = self._contains(family, relative) or self._contains(family, content)
            if not related:
                continue
            directory_identities = list(path.parent.relative_to(root).parts)
            explicit = self._models([*identity_sources, *directory_identities], family)
            # Only bounded, explicit model labels from prose count here. A date
            # elsewhere in the paragraph never becomes a product year. A less
            # specific same-model label is compatible with a precise query.
            for model in self._body_models(content, family):
                if not self._contains(model, query) and not any(
                    self._model_key(model) == self._model_key(existing) for existing in explicit
                ):
                    explicit.append(model)
            for model in explicit:
                canonical = next((name for name in candidates
                                  if self._model_key(name) == self._model_key(model)), model)
                candidates.setdefault(canonical, []).append({
                    "document_title": path.name, "source_ref": relative,
                })
            exact_identity = any(self._contains(query, text) for text in identity_sources)
            exact_directory = self._dedicated_directory(path.parent.relative_to(root), query)
            body_match = self._contains(query, content)
            conflicting_identity = any(
                self._model_key(model) != self._model_key(query)
                and self._model_key(model) != self._model_key(family)
                for model in explicit
            )
            comparison = bool(re.search(r"竞品|跨产品|产品对比|型号对比", relative)) or bool(
                re.search(r"\b(?:vs\.?|versus)\b", first_title, re.I)
            )
            if ambiguous_query:
                continue
            if not (exact_identity or (exact_directory and body_match)) or conflicting_identity or comparison:
                excluded += 1
                if exact_identity and conflicting_identity:
                    warnings.append(f"资料存在多个型号身份，未纳入确定事实：{relative}")
                continue
            evidence = {
                "filename": self._contains(query, path.stem),
                "relative_directory": exact_directory,
                "markdown_title": self._contains(query, first_title),
                "explicit_identity_field": any(self._contains(query, x) for x in identity_fields),
                "body_full_model": body_match,
            }
            records.append((path, content, {
                "media_id": None, "product_model": query,
                "document_title": path.name,
                "document_type": path.suffix.lower().lstrip("."),
                "content": content, "source": relative, "source_ref": relative,
                "media": [], "model_evidence": evidence,
            }))

        result["candidate_models"] = [
            {"product_model": model, "sources": sources, "recommended": False}
            for model, sources in sorted(candidates.items())
        ]
        if ambiguous_query:
            result["status"] = "conflict" if len(candidates) > 1 else "needs_input"
            result["missing_information"].append("请提供包含版本或配置的完整产品型号。")
            warnings.append("查询为产品系列泛称，未将不同版本资料合并为确定事实。")
            return result
        if excluded:
            warnings.append(f"已排除 {excluded} 份泛称、跨型号或无法证明属于精确型号的资料。")
        matching_variants = [model for model in candidates if self._contains(query, model)]
        if len(matching_variants) > 1:
            result["status"] = "conflict"
            result["missing_information"].append("该查询仍对应多个明确版本或配置，请进一步确认完整型号。")
            warnings.append("存在更具体的产品配置候选，未用通用版本资料掩盖配置歧义。")
            return result
        result["documents"] = [record[2] for record in records]
        if not records:
            result["missing_information"].append("未找到可确认属于该精确型号的本地正文资料。")
            return result
        result["selected_product_model"] = query
        result["status"] = "success"
        # Only this selected model's source documents provide facts.
        result["candidate_models"] = [{
            "product_model": query, "recommended": False,
            "sources": [{"document_title": doc["document_title"], "source_ref": doc["source_ref"]}
                        for doc in result["documents"]],
        }]
        self._match_images(root, records, image_files, query, family, result)
        return result

    @staticmethod
    def _compact(value: str) -> str:
        return re.sub(r"[\W_]+", "", value.casefold())

    @classmethod
    def _model_key(cls, value: str) -> str:
        return cls._compact(re.sub(r"^HUAWEI\s*", "", value.strip(), flags=re.I))

    @classmethod
    def _contains(cls, query: str, value: str) -> bool:
        needle = cls._model_key(query)
        return bool(needle and needle in cls._compact(value))

    @staticmethod
    def _family(query: str) -> str:
        match = re.search(r"MateBook\s+[A-Za-z0-9]+(?:\s+Pro)?", query, re.I)
        return match.group(0) if match else query.removeprefix("HUAWEI ").strip()

    @classmethod
    def _models(cls, identities: list, family: str) -> list:
        """Extract literal identities from dedicated names, never harvest specs."""
        models = []
        family_pattern = r"\s*".join(re.escape(part) for part in family.split())
        pattern = re.compile(r"(?:HUAWEI\s+)?" + family_pattern + r"(?P<tail>[^\r\n|｜\]#]*)", re.I)
        for identity in identities:
            for match in pattern.finditer(identity):
                full = match.group(0).strip()
                tail = match.group("tail").strip()
                if not tail or re.match(r"(?:长页|Huawei\b|An\s+honest\b)", tail, re.I):
                    continue
                # Remove document labels, not processor/memory/storage identity.
                full = re.sub(r"\s*[-－—]\s*(?:产品事实|营销指南|(?:官方公开)?价格卡)$", "", full).strip()
                full = re.sub(r"\s+y\s+el\s+.*$", "", full, flags=re.I).strip()
                if cls._model_key(full) != cls._model_key(family) and not any(
                    cls._model_key(full) == cls._model_key(existing) for existing in models
                ):
                    models.append(full)
        return models

    @classmethod
    def _body_models(cls, content: str, family: str) -> list:
        """Find explicit model-year/edition labels without absorbing prose."""
        # Asset destinations describe resources, not prose facts. Contradictory
        # image names are checked independently and remain unknown images.
        content = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", content)
        content = re.sub(r"<img\b[^>]*>", "", content, flags=re.I)
        content = re.sub(r"(?m)^\s*\[[^\]]+\]:.*$", "", content)
        prefix = r"(?:HUAWEI[ \t]+)?" + r"[ \t]*".join(re.escape(part) for part in family.split())
        patterns = (
            re.compile(prefix + r"[ \t]*(?:19|20)\d{2}(?!\d|[-/.]\d|年\d)", re.I),
            re.compile(prefix + r"[ \t]+(?-i:(?:[A-Z][A-Za-z0-9]*[ \t-]+){1,5}Edition)\b", re.I),
            re.compile(prefix + r"[ \t]+[A-Za-z0-9\u3400-\u9fff· \t-]{1,48}?版(?!本)", re.I),
        )
        prose = re.compile(
            r"\b(?:is|was|has|with|offers|features|supports|review|the)\b"
            r"|是|为|采用|配备|支持|适合|拥有|使用|发布|日期|抓取|更新|属于|文章|资料|参数|提供|需要|建议|推荐",
            re.I,
        )
        models = []
        for pattern in patterns:
            for match in pattern.finditer(content):
                value = match.group(0).strip()
                tail = re.sub(r"^" + prefix, "", value, count=1, flags=re.I).strip()
                if tail not in {"最新版", "新版", "旧版"} and not prose.search(tail) and not any(
                    cls._model_key(value) == cls._model_key(existing) for existing in models
                ):
                    models.append(value)
        return models

    @classmethod
    def _dedicated_directory(cls, relative: Path, query: str) -> bool:
        target = cls._model_key(query)
        return any(cls._model_key(re.sub(r"^\d+[-_. ]*", "", part)) == target for part in relative.parts)

    @staticmethod
    def _ignored_name(name: str) -> bool:
        lowered = name.casefold()
        return (
            name.startswith((".", "~", "#"))
            or lowered in {"__macosx", "__macosx__", "thumbs.db", "desktop.ini"}
            or lowered.endswith(("~", ".tmp", ".temp", ".swp", ".swo", ".bak", ".part"))
            or any(marker in lowered for marker in (".tmp.", ".temp.", ".swp.", ".bak."))
        )

    @staticmethod
    def _is_link(path: Path) -> bool:
        try:
            info = path.lstat()
            return stat.S_ISLNK(info.st_mode) or bool(
                getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
            )
        except OSError:
            return True

    @staticmethod
    def _is_hidden(path: Path) -> bool:
        try:
            return bool(getattr(path.lstat(), "st_file_attributes", 0)
                        & getattr(stat, "FILE_ATTRIBUTE_HIDDEN", 0x2))
        except OSError:
            return True

    def _root(self) -> Optional[Path]:
        try:
            if (self._configured_path is None or self._is_link(self._configured_path)
                    or self._is_hidden(self._configured_path)):
                return None
            root = self._configured_path.resolve(strict=True)
            return root if root.is_dir() else None
        except (OSError, RuntimeError):
            return None

    @classmethod
    def _safe_file(cls, root: Path, path: Path) -> bool:
        try:
            relative = path.relative_to(root)
            if any(cls._ignored_name(part) for part in relative.parts):
                return False
            current = root
            for part in relative.parts:
                current = current / part
                if cls._is_link(current) or cls._is_hidden(current):
                    return False
            return path.resolve(strict=True).is_relative_to(root) and path.is_file()
        except (OSError, ValueError, RuntimeError):
            return False

    def _scan(self, root: Path, warnings: list) -> tuple:
        texts, images = [], []
        def on_error(_error):
            if "部分本地目录无法读取，已跳过。" not in warnings:
                warnings.append("部分本地目录无法读取，已跳过。")
        for directory, names, files in os.walk(root, topdown=True, onerror=on_error, followlinks=False):
            folder = Path(directory)
            names[:] = sorted(name for name in names if not self._ignored_name(name)
                              and not self._is_link(folder / name) and not self._is_hidden(folder / name))
            for name in sorted(files):
                path = folder / name
                if self._ignored_name(name) or path.suffix.lower() not in self._TEXT | self._IMAGES:
                    continue
                if not self._safe_file(root, path):
                    continue
                (texts if path.suffix.lower() in self._TEXT else images).append(path)
        return texts, images

    def _read_text(self, root: Path, path: Path, warnings: list) -> Optional[str]:
        relative = path.relative_to(root).as_posix()
        try:
            if not self._safe_file(root, path):
                return None
            with path.open("rb") as source:
                data = source.read(self._MAX_TEXT_BYTES + 1)
            if len(data) > self._MAX_TEXT_BYTES:
                warnings.append(f"文本超过只读大小限制，已跳过：{relative}")
                return None
            return data.decode("utf-8-sig")
        except (OSError, UnicodeError):
            warnings.append(f"文本无法按 UTF-8 读取，已跳过：{relative}")
            return None

    @staticmethod
    def _image_references(content: str) -> list:
        references = re.findall(r"!\[[^\]]*\]\(\s*(<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)", content)
        labels = re.findall(r"!\[[^\]]*\]\[([^\]]+)\]", content)
        definitions = dict(re.findall(r"(?m)^\s*\[([^\]]+)\]:\s*(<[^>]+>|\S+)", content))
        references.extend(definitions[label] for label in labels if label in definitions)
        references.extend(re.findall(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", content, re.I))
        return references

    def _match_images(self, root, records, image_files, query, family, result):
        images_by_path = {path.relative_to(root).as_posix(): path for path in image_files}
        referenced = {}
        for path, content, document in records:
            for reference in self._image_references(content):
                try:
                    parsed = urlsplit(reference.strip("<>"))
                except ValueError:
                    continue
                # Absolute http(s) image references in KB markdown are externally
                # served assets: expose them as media entries carrying the URL so
                # downstream readability checks can probe them. Confirmation still
                # requires the asset name to identify the exact model.
                if parsed.scheme in {"http", "https"} and parsed.netloc:
                    raw_url = reference.strip("<>")
                    decoded_path = unquote(parsed.path)
                    asset_name = Path(decoded_path).name or raw_url
                    confirmed = self._contains(query, decoded_path)
                    media = {
                        "name": asset_name, "url": raw_url, "source": path.relative_to(root).as_posix(),
                        "source_ref": decoded_path.lstrip("/") or asset_name, "product_model": query if confirmed else None,
                        "status": "confirmed" if confirmed else "unknown",
                        "match_basis": "absolute_url_reference" if confirmed else None,
                    }
                    if not any(existing.get("source_ref") == raw_url for existing in result["media"]):
                        result["media"].append(media)
                        result["image_counts"][media["status"]] += 1
                    continue
                if parsed.scheme or parsed.netloc:
                    continue
                decoded = unquote(parsed.path)
                if not decoded or Path(decoded).is_absolute() or ":" in decoded:
                    continue
                try:
                    original = Path(os.path.abspath(path.parent / decoded))
                    if not self._safe_file(root, original):
                        continue
                    candidate = original.resolve(strict=True)
                    relative = candidate.relative_to(root).as_posix()
                except (OSError, ValueError, RuntimeError):
                    continue
                if relative in images_by_path and self._safe_file(root, candidate):
                    referenced.setdefault(relative, []).append(document)
        for relative, path in images_by_path.items():
            name_match = self._contains(query, path.stem)
            directory_match = self._dedicated_directory(path.parent.relative_to(root), query)
            matched_docs = referenced.get(relative, [])
            family_pattern = r"\s*".join(re.escape(part) for part in family.split())
            contradictory_name = bool(re.search(
                r"(?:^|[-_\s])(?:vs\.?|versus)(?:[-_\s]|$)|对比|比较|跨型号", path.stem, re.I,
            )) or len(re.findall(family_pattern, path.stem, re.I)) > 1 or any(
                not self._contains(query, model) for model in self._models([path.stem], family)
            )
            nearby = any(path.parent == document_path.parent or (
                path.parent.parent == document_path.parent
                and path.parent.name.casefold() in {"images", "img", "assets", "media"}
            ) for document_path, _, _ in records)
            if not (matched_docs or name_match or directory_match or self._contains(family, relative) or nearby):
                continue
            confirmed = bool(matched_docs or name_match or directory_match) and not contradictory_name
            media = {
                "name": path.name, "url": None, "source": relative,
                "source_ref": relative, "product_model": query if confirmed else None,
                "status": "confirmed" if confirmed else "unknown",
                "match_basis": ("markdown_reference" if matched_docs else (
                    "full_model_filename" if name_match else "dedicated_directory" if directory_match else None
                )) if confirmed else None,
            }
            result["media"].append(media)
            result["image_counts"][media["status"]] += 1
            for document in matched_docs:
                document["media"].append(dict(media))
            if confirmed and not matched_docs:
                for _, _, document in records:
                    if self._dedicated_directory(Path(document["source_ref"]).parent, query):
                        document["media"].append(dict(media))
        if result["image_counts"]["unknown"]:
            result["warnings"].append(
                f"{result['image_counts']['unknown']} 张相关图片无法确认属于精确型号，已标记 unknown；不计入已确认图片。"
            )
