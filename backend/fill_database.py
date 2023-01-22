import argparse
import asyncio
import os
import sys
import re
import pandas as pd
from tqdm import tqdm
import ast
import time

from db import crud, schemas
from db.database import Base, engine, get_session


COLNAMES = ["id", "title", "authors", "venue", "year", "keywords", "fos",
            "references", "n_citation", "page_start", "page_end", "lang",
            "volume", "issue", "issn", "isbn", "doi", "pdf", "url", "abstract"]

CONTAINER_COLNAMES = ["venue", "authors", "keywords", "fos", "references", "url"]


def prepare(input_file, output_file):
    for line in input_file:
        line = re.sub(r"\"_id\"", '"id"', line)
        line = re.sub(r"\"name_d\"", '"name"', line)
        line = re.sub(r"NumberInt\(([0-9]+)\)", r"\1", line)
        output_file.write(line)


def remove_incomplete_attributes(paper: dict):
    venue = paper.get("venue")
    # beware of the empty dict case!
    # (it won't pass "if venue" check, but should be processed)
    if venue is not None:
        if "id" not in venue:
            del paper["venue"]

    authors = paper.get("authors")
    if authors:
        authors[:] = [author for author in authors if "id" in author]


def parse_csv_and_add_to_database(filename, session, total_num_papers=6000):
    df = pd.read_csv(filename)
    st = time.time()
    print("Filling DB...", file=sys.stderr)
    for counter, paper in tqdm(enumerate(df.iterrows()), total=total_num_papers, file=sys.stderr):
        if counter == total_num_papers:
            break
        paper = dict(paper[1])
        # paper = {k: ast.literal_eval(v) if k in CONTAINER_COLUMNSS else v for k, v in paper.items()}
        for k, v in paper.items():
            try:
                paper[k] = ast.literal_eval(v)
            except (SyntaxError, ValueError):
                continue
            finally:
                if k in CONTAINER_COLNAMES and not isinstance(paper[k], (list, dict, tuple)):
                    paper[k] = list()
        remove_incomplete_attributes(paper)
        crud.create_paper(schemas.Paper(**paper), session)
    print(f"DB filled with {total_num_papers} papers in {time.time() - st:.3f}s", file=sys.stderr)


def fill_database_with_csv(csv_file, total_num_papers=6000):
    Base.metadata.create_all(engine)
    with get_session() as session:
        parse_csv_and_add_to_database(csv_file, session, total_num_papers)
    engine.dispose()


def fill_database(file, total_num_papers=6000):
    print(f"Row papers file for db filling: {file}", file=sys.stderr)
    fill_database_with_csv(file, total_num_papers)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--filename", default="/data/preprocessed_top_50k_papers_by_n_citation.csv")
    args = parser.parse_args()

    fill_database(args.filename, 2000)
