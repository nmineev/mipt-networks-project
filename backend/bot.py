import logging
import os
import sys
import pprint
from aiogram import Bot, Dispatcher, types
from aiogram.utils import executor
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.utils import markdown
from aiogram.dispatcher.filters import Text
from emoji import emojize
from db.crud import create_user
from db.database import Base, engine, get_session
from db.db_utils import *
from db.crud import update_by_id, insert_user_paper_interaction, read_by_id
import random
random.seed(123)
import db.models
import recommender
from sqlalchemy import desc


def get_feedback_keyboard(paper_id: str):
    buttons = [
        [
            types.InlineKeyboardButton(text=emojize("like :thumbs_up:"),
                                       callback_data=f"feedback_like_{paper_id}"),
            types.InlineKeyboardButton(text=emojize("dislike :thumbs_down:"),
                                       callback_data=f"feedback_dislike_{paper_id}")
        ]
    ]
    keyboard = types.InlineKeyboardMarkup(inline_keyboard=buttons)
    return keyboard


def get_menu_keyboard():
    buttons = [
        [types.KeyboardButton(text=emojize(":books: What should i read next?"))],
        [types.KeyboardButton(text=emojize(":fire: Hot papers"))],
        [types.KeyboardButton(text=emojize(":astronaut: Sign me up"))],
    ]
    keyboard = types.ReplyKeyboardMarkup(keyboard=buttons,
                                         resize_keyboard=True,
                                         input_field_placeholder="Choose action")
    return keyboard


def paper_markdowner(paper: dict):
    content = list()
    if paper["title"]:
        content.append(markdown.bold(paper["title"]))
    if paper["abstract"]:
        content.append(markdown.text(paper["abstract"][:300]+"..."))
    tail = "\n"
    if paper["authors"]:
        tail += paper["authors"][0]["name"] + " et al., "
    if paper["year"]:
        tail += str(paper["year"])
    content.append(markdown.text(tail))
    if paper["url"] and len(paper["url"]) > 2:
        paper_urls = paper["url"][1:-1]
        paper_urls = paper_urls.split(',')
        content.append(markdown.link("Read full paper here", paper_urls[0]))
    return markdown.text(*content, sep='\n')


API_TOKEN = os.environ["TOKEN"]

# Configure logging
logging.basicConfig(level=logging.INFO)

Base.metadata.create_all(engine)

# Initialize bot and dispatcher
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)


@dp.message_handler(commands=["start", "help"])
async def send_welcome(message: types.Message):
    await message.reply("""*Welcome to papers recommender bot!*\n
If you want to find paper by some parameter use command `/find_by`
For example: `/find_by year 2007`
Currently this function supports year/name (author name)\n
To call menu with buttons -- print `/menu`\n
Get trending papers -- tap _Hot papers_ button in the menu\n
To get simple recommendations about papers, tap _What should i read next?_ button\n
If you want more precise recommendations, sign up firstly, so i will 
track your like-dislike feedbacks, carefully save it in my database 
and run more complex models to perfectly follow your tastes""",
                        reply_markup=get_menu_keyboard(),
                        parse_mode=types.ParseMode.MARKDOWN)


@dp.message_handler(Text(equals=emojize(":astronaut: Sign me up"), ignore_case=True),
                    content_types=[types.ContentType.TEXT])
async def sign_up_user(message: types.Message):
    with get_session() as session:
        if not check_user_exists(message.from_user.id, session):
            await message.answer(f"You are not registered yet, I will add you to my database now."
                                 "Dont worry, it's safe.")
            create_user(message.from_user.id, session)
        else:
            await message.answer("You are already signed")


@dp.message_handler(commands=["menu"])
async def send_menu(message: types.Message):
    await message.answer("Choose action, please", reply_markup=get_menu_keyboard(),
                         parse_mode=types.ParseMode.MARKDOWN)


@dp.message_handler(commands=["find_by"], content_types=[types.ContentType.TEXT])
async def find_by(message: types.Message):
    _, query, value = message.text.split(' ', 2)
    papers = []
    with get_session() as session:
        if query == "year":
            papers = find_by_year(int(value), session)
        elif query == "name":
            papers = find_by_author(value, session)
        # elif query == "topic":
        #     papers = find_by_topic(value, session)
    if len(papers):
        random.shuffle(papers)
        for paper in papers[:5]:
            await message.reply(paper_markdowner(paper),#pprint.pformat(paper, depth=3, indent=4)[1:-1],
                                reply_markup=get_feedback_keyboard(paper["id"]),
                                parse_mode=types.ParseMode.MARKDOWN)
    else:
        await message.reply("No such papers")


@dp.message_handler(Text(equals=emojize(":fire: Hot papers"), ignore_case=True))
@dp.message_handler(commands=["hot_papers"])
async def get_hot_papers(message: types.Message):
    with get_session() as session:
        num_papers = 5
        sorted_papers_by_citation = session.query(db.models.Paper).order_by(db.models.Paper.n_citations)
        if sorted_papers_by_citation is not None:
            for paper_num, paper in enumerate(sorted_papers_by_citation):
                await message.reply(paper_markdowner(paper.as_dict()),
                                    reply_markup=get_feedback_keyboard(paper.id),
                                    parse_mode=types.ParseMode.MARKDOWN)
                if paper_num + 1 == num_papers:
                    break
        else:
            await message.reply("Ups, something went wrong, we are already working on it")


@dp.message_handler(Text(equals=emojize(":books: What should i read next?"), ignore_case=True))
@dp.message_handler(commands=["what_should_i_read_next"])
async def recommend_paper(message: types.Message):
    with get_session() as session:
        last_liked_paper = None
        readed_papers = list()
        user = session.query(db.models.User).filter_by(tg_id=message.from_user.id).one_or_none()
        if user is not None:
            last_liked_paper = session.query(db.models.Paper).filter_by(id=user.last_like_paper_id).one_or_none()
            if last_liked_paper is not None:
                last_liked_paper = {"title": last_liked_paper.title, "abstract": last_liked_paper.abstract}
            user_interactions = session.query(db.models.UserPaper).filter_by(user_id=user.id)
            if user_interactions is not None:
                readed_papers = [interaction.paper_id for interaction in user_interactions]
        recommended_paper_ids = recommender.get_recommended_paper_id(last_liked_paper,
                                                                     readed_papers)
        recommended_paper = None
        for recommended_paper_id in recommended_paper_ids:
            recommended_paper = session.query(db.models.Paper).filter_by(id=recommended_paper_id).one_or_none()
            if recommended_paper is not None:
                break
        if recommended_paper is None:
            await message.reply("Ups, something went wrong, we are already working on it")
        else:
            await message.reply(paper_markdowner(recommended_paper.as_dict()),
                                reply_markup=get_feedback_keyboard(recommended_paper_id),
                                parse_mode=types.ParseMode.MARKDOWN)


@dp.callback_query_handler(Text(startswith="feedback_"))
async def callbacks_feedback_on_paper(
        callback: types.CallbackQuery,
):
    _, feedback_value, paper_id = callback.data.split("_")
    with get_session() as session:
        user = session.query(db.models.User).filter_by(tg_id=callback.from_user.id).one_or_none()
        if feedback_value == "like" and user is not None:
            update_by_id(user.id, {"last_like_paper_id": paper_id}, "user", session)
            insert_user_paper_interaction(user.id, paper_id, True, session)
        elif feedback_value == "dislike" and user is not None:
            if user.last_like_paper_id == paper_id:
                update_by_id(user.id, {"last_like_paper_id": None}, "user", session)
            insert_user_paper_interaction(user.id, paper_id, False, session)
    await callback.answer()


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
