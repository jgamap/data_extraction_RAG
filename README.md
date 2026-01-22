
<!-- badges: start -->

[![Lifecycle:
experimental](https://img.shields.io/badge/lifecycle-experimental-orange.svg)](https://lifecycle.r-lib.org/articles/stages.html#experimental)
<!-- badges: end -->

## GROBID Installation
This application was developed to use using [GROBID](https://grobid.readthedocs.io/en/latest/). BROBID is a machine learning library for extracting, parsing, and re-structuring raw pdfs into structured XML/TEI encoded documents with a main focus on scientific papers.

GROBID must be instantiated and run using [Docker](https://www.docker.com). You can find instructions on how to install Docker [here](https://www.docker.com/get-started/). 

## App installation

**Install requirements**
Run this in your terminal:

```
pip install -r requirements.txt
```
**Set your OpenAI API key**
```
export OPENAI_API_KEY=your_api_key_value
```
**Set up your `.dockerignore` file**
Add any file or directory that is not needed for the app

```
.venv
__pycache__
*.pyc
*.pyo
*.pyd
.DS_Store
.git
.gitignore
```
**Build your app image using docker**
```
docker compose build
```

**Start all services**
```
docker compose up
```
Your paper extraction app can now be assessed through Docker Desktop app or at http://localhost:8000
