"""An OpenRouter-backed `LLM` for the vendored FunSearch sampler.

`implementation/sampler.py` ships an abstract `LLM` whose `_draw_sample` raises
NotImplementedError ("Must provide a language model") -- the paper used a
frozen, fine-tuned-for-code PaLM 2 variant (Codey) through an internal API.
Here `_draw_sample` calls the project's OpenRouter model through `common.chat`.

Two adaptations are needed because Codey is a *code-completion* model and ours
is a chat model:

* the paper's prompt is raw source code that ends with the header of
  `priority_v{k}`; we send exactly that text as the user message and put the
  "continue this code, body only" instruction in the system message;
* chat models like to answer with prose and markdown fences, so
  `clean_completion` strips them and re-indents, leaving a body that the
  vendored `_trim_function_body` can parse.  Everything it cannot rescue is
  discarded downstream by the evaluator, exactly as in the paper.
"""
from __future__ import annotations

import re
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import common
from funsearch.implementation import sampler as sampler_lib

SYSTEM_PROMPT = (
    "You are a Python code completion engine used inside an evolutionary program "
    "search. The user message is a Python file that ends with the header of the "
    "function you must write. Reply with the BODY of that last function ONLY: "
    "indented Python statements starting at two spaces, ending with a `return`. "
    "Do not repeat the `def` line, do not add a docstring, do not add any prose, "
    "explanation or markdown fences, and do not define or call any other function. "
    "The body must be deterministic (no randomness) and must only use the arguments "
    "and the modules imported at the top of the file. Write a new, substantially "
    "different and more inventive implementation than the ones shown -- never a copy."
)

_FENCE_RE = re.compile(r"```(?:python|py)?\s*\n(.*?)(?:```|\Z)", re.S)


def clean_completion(text: str) -> str:
    """Turns a chat reply into the indented function body the trimmer expects."""
    text = text.replace("\n[TRUNCATED: hit max_tokens]", "")
    blocks = _FENCE_RE.findall(text)
    if blocks:
        text = max(blocks, key=len)          # keep the longest fenced block
    text = text.replace("```", "")
    lines = text.split("\n")

    # Drop everything up to and including a `def ...:` header, if the model
    # helpfully re-emitted one (possibly with a multi-line signature).
    for i, line in enumerate(lines):
        if line.lstrip().startswith("def "):
            j = i
            while j < len(lines) and not lines[j].rstrip().endswith(":"):
                j += 1
            lines = lines[j + 1:]
            break
        if line.strip():                      # first real line is not a header
            break

    while lines and not lines[0].strip():
        lines.pop(0)
    # Drop a re-emitted docstring; the template keeps its own.
    if lines and lines[0].lstrip()[:3] in ('"""', "'''"):
        quote = lines[0].lstrip()[:3]
        stripped = lines[0].strip()
        end = 0 if len(stripped) > 3 and stripped.endswith(quote) else None
        if end is None:
            for k in range(1, len(lines)):
                if quote in lines[k]:
                    end = k
                    break
        if end is not None:
            lines = lines[end + 1:]
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""

    # `Function.__str__` emits the docstring at a fixed two-space indent, so the
    # body has to sit at exactly two spaces or the assembled program will not parse.
    body = textwrap.dedent("\n".join(lines))
    return "\n".join("  " + line if line.strip() else "" for line in body.split("\n")) + "\n"


class OpenRouterLLM(sampler_lib.LLM):
    """`LLM` subclass drawing continuations from the project's OpenRouter model."""

    def __init__(self, samples_per_prompt: int = 1, temperature: float = 1.0,
                 max_tokens: int = 400, tag: str = "funsearch-llm",
                 max_workers: int = 4, retries: int = 2) -> None:
        super().__init__(samples_per_prompt)
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.tag = tag
        self.max_workers = max_workers
        self.retries = retries
        self.records: list[dict[str, Any]] = []
        self.errors: list[str] = []

    def _draw_sample(self, prompt: str) -> str:
        """One continuation. A call that keeps failing yields an empty sample.

        FunSearch already discards anything it cannot score, so a failed API call
        is just one more discarded sample rather than a crashed experiment; the
        budget is halved on each retry because the usual failure is a provider
        refusing the requested `max_tokens`.
        """
        t0, raw, budget = time.time(), "", self.max_tokens
        for attempt in range(self.retries + 1):
            try:
                raw = common.chat(prompt, SYSTEM_PROMPT, temperature=self.temperature,
                                  max_tokens=budget, tag=self.tag, reasoning="off")
                break
            except Exception as exc:  # noqa: BLE001 - any API failure is a lost sample
                self.errors.append(f"{type(exc).__name__}: {exc}"[:300])
                budget = max(200, budget // 2)
                time.sleep(1.5 * (attempt + 1))
        body = clean_completion(raw)
        self.records.append({"prompt_chars": len(prompt), "raw": raw, "body": body,
                             "seconds": round(time.time() - t0, 1)})
        return body

    def draw_samples(self, prompt: str) -> list[str]:
        """Same contract as the base class, but the k samples go out concurrently."""
        if self._samples_per_prompt == 1:
            return [self._draw_sample(prompt)]
        with ThreadPoolExecutor(max_workers=min(self.max_workers, self._samples_per_prompt)) as pool:
            return list(pool.map(lambda _: self._draw_sample(prompt),
                                 range(self._samples_per_prompt)))


class OpenRouterSampler(sampler_lib.Sampler):
    """`Sampler` with a real LLM and a bounded `sample_once` instead of `while True`."""

    def __init__(self, database, evaluators, llm: sampler_lib.LLM) -> None:
        super().__init__(database, evaluators, llm._samples_per_prompt)
        self._llm = llm       # the base class installed the abstract LLM; replace it

    def sample_once(self) -> dict[str, Any]:
        """One iteration of the paper's sampler loop: prompt -> samples -> analyse.

        Body copied from `Sampler.sample`, with the `while True` removed and the
        prompt/results returned so a notebook can look at them.
        """
        import numpy as np

        prompt = self._database.get_prompt()
        samples = self._llm.draw_samples(prompt.code)
        results = []
        for sample in samples:
            chosen_evaluator = np.random.choice(self._evaluators)
            results.append(chosen_evaluator.analyse(
                sample, prompt.island_id, prompt.version_generated))
        return {"prompt": prompt, "samples": samples, "results": results}
