from flask import Flask, render_template, request
import logging
import nltk
from nltk.corpus import stopwords
from textblob import TextBlob
from spellchecker import SpellChecker
from transformers import GPT2Tokenizer, GPTNeoForCausalLM
from sklearn.metrics.pairwise import cosine_similarity
import torch
import numpy as np
import requests
from bs4 import BeautifulSoup
import warnings
import re
import asyncio
import nest_asyncio
from flask_caching import Cache

warnings.filterwarnings("ignore")
nltk.download('punkt')
nltk.download('stopwords')
nest_asyncio.apply()

app = Flask(__name__)

# Configure caching
cache = Cache(app, config={"CACHE_TYPE": "simple", "CACHE_DEFAULT_TIMEOUT": 300})


#################### FUNCTION : Get Article Content from URL ##################

@cache.memoize()
def get_article(article_url):
    response = requests.get(article_url)
    if response.status_code == 200:
        soup = BeautifulSoup(response.content, 'html.parser')
        para_tags = soup.find_all('p')
        all_para = [para.get_text() for para in para_tags]
        article_text = "".join(all_para)
        article_text = re.sub(r'<.*?>|\n|\t', '', article_text)
        return article_text
    else:
        print('----Something went wrong----')
        return False


#################### FUNCTION : Check that article is generated by AI ##################

async def is_generated_by_language_model(article):
    # Load GPT-3.5 tokenizer and model
    tokenizer = GPT2Tokenizer.from_pretrained("EleutherAI/gpt-neo-1.3B")
    model = GPTNeoForCausalLM.from_pretrained("EleutherAI/gpt-neo-1.3B")

    # Tokenize the original article
    inputs = tokenizer.encode(article, return_tensors="pt", add_special_tokens=True)

    # Generate text using the GPT-2 model
    with torch.no_grad():
        outputs = model.generate(inputs, max_length=100, num_return_sequences=1)

    # Decode the generated tokens
    generated_text = tokenizer.decode(outputs[0], skip_special_tokens=True)

    # Truncate or pad the generated text to match the length of the original article
    max_length = max(len(inputs[0]), len(outputs[0]))
    inputs = torch.nn.functional.pad(inputs, (0, max_length - len(inputs[0])))
    outputs = torch.nn.functional.pad(outputs, (0, max_length - len(outputs[0])))

    # Calculate cosine similarity between original article and generated text
    embeddings = model.get_input_embeddings()(inputs).squeeze().detach().numpy()
    generated_embeddings = model.get_input_embeddings()(outputs).squeeze().detach().numpy()

    # Reshape embeddings to 2D arrays
    embeddings = embeddings.reshape(1, -1)
    generated_embeddings = generated_embeddings.reshape(1, -1)

    similarity = cosine_similarity(embeddings, generated_embeddings)[0, 0]

    # Map similarity score to effort score on a scale of 0 to 1
    effort_score = (similarity + 1) / 2  # Mapping from [-1, 1] to [0, 1]
    print(effort_score)

    if effort_score > 0.7:
        return True
    else:
        return False


################ FUNCTION : Evaluate the Quality of the Article ##################

@cache.memoize()
def evaluate_article_quality(article, is_written_by_chatgpt,relevant_keywords_list):
    # Readability score
    readability_score = TextBlob(article).sentiment.polarity

    # Vocabulary richness (Simple measure: Count unique words)
    words = TextBlob(article).words
    unique_words_count = len(set(words))
    total_words_count = len(words)
    vocabulary_score = unique_words_count / total_words_count

    # Spelling check using pyspellchecker
    spell = SpellChecker()
    misspelled_words = spell.unknown(words)
    spelling_error_count = len(misspelled_words)
    spelling_error_score = 1.0 - (spelling_error_count / total_words_count)


    # relevant_keywords = ["study plan", "IBPS Clerk", "academic success", "exam", "2023"]
    relevance_score = sum(keyword.lower() in article.lower() for keyword in relevant_keywords_list) / len(relevant_keywords_list)

    # Effort check for content written by ChatGPT
    effort_score = 1.0 if not is_written_by_chatgpt else 0.0

    # Calculate the quality score (You can customize the weights as needed)
    quality_score = (
        0.4 * readability_score + 0.1 * vocabulary_score + 0.3 * relevance_score + 0.1 * effort_score + 0.1 * spelling_error_score 
    )

    # Scale the quality score to percentage (0 to 100)
    score_percentage = round((quality_score + 1) * 50,0)  # Mapping from [-1, 1] to [0, 100]

    # Calculate the contribution of each score to the overall score
    contributions = {
    "Readability": round((0.4 * readability_score / quality_score) * 100, 2),
    "Vocabulary Richness": round((0.1 * vocabulary_score / quality_score) * 100, 2),
    "Relevance": round((0.3 * relevance_score / quality_score) * 100, 2),
    "Generated by ChatGPT": round((0.1 * effort_score / quality_score) * 100, 2),
    "Spelling Error": round((0.1 * spelling_error_score / quality_score) * 100, 2),
    }

    return score_percentage, contributions



@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        article_url = request.form["article_url"]
        relevant_keywords_input = request.form["relevant_keywords"]
        relevant_keywords_list = [keyword.strip() for keyword in relevant_keywords_input.split(",")]

        # Fetch the article content using the URL (You may use libraries like requests or urllib for this)
        article_text = get_article(article_url)

        # Use asyncio to call the is_generated_by_language_model asynchronously
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        is_written_by_chatgpt = loop.run_until_complete(is_generated_by_language_model(article_text))

        # Calculate Effort Score and Contributions
        score_percentage, contributions = evaluate_article_quality(article_text, is_written_by_chatgpt, relevant_keywords_list)

        return render_template("result.html", effort_score=score_percentage, contributions=contributions)

    return render_template("index.html")


if __name__ == "__main__":
    app.run(debug=False)