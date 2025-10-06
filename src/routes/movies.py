from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Query,
    status,
    Body
)
from pydantic import ValidationError
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from database import get_db, MovieModel
from database.models import (
    CountryModel,
    GenreModel,
    ActorModel,
    LanguageModel
)
from schemas.movies import (
    MovieListItemSchema,
    MovieListResponseSchema,
    MovieDetailSchema,
    MovieCreateRequestSchema,
    MovieUpdateSchema
)

router = APIRouter()


@router.get(
    path="/movies/",
    response_model=MovieListResponseSchema,
    status_code=status.HTTP_200_OK
)
async def get_movies(
        db: AsyncSession = Depends(get_db),
        page: int = Query(
            default=1,
            ge=1,
            description="Page number must be >= 1"
        ),
        per_page: int = Query(
            default=10,
            ge=1,
            le=20,
            description="Items per page must be between 1 and 20"
        )
):
    total_items_result = await db.execute(
        select(func.count(MovieModel.id))
    )
    total_items = total_items_result.scalar_one()

    if total_items == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No movies found."
        )

    total_pages = (total_items + per_page - 1) // per_page
    offset = (page - 1) * per_page

    if offset >= total_items:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No movies found."
        )

    base_url = "/theater/movies/"
    prev_page = (
        f"{base_url}?page={page - 1}&per_page={per_page}"
        if page > 1 else None
    )

    next_page = (
        f"{base_url}?page={page + 1}&per_page={per_page}"
        if page < total_pages else None
    )

    result_movies = await db.execute(
        select(MovieModel)
        .order_by(MovieModel.id.desc())
        .offset(offset)
        .limit(per_page)
    )

    movies = result_movies.scalars().all()
    movie_schemas = [
        MovieListItemSchema.model_validate(movie)
        for movie in movies
    ]

    return MovieListResponseSchema(
        movies=movie_schemas,
        prev_page=prev_page,
        next_page=next_page,
        total_pages=total_pages,
        total_items=total_items
    )


async def get_movie_by_id(movie_id: int, db: AsyncSession) -> MovieModel:
    result = await db.execute(
        select(MovieModel)
        .options(
            joinedload(MovieModel.country),
            selectinload(MovieModel.genres),
            selectinload(MovieModel.actors),
            selectinload(MovieModel.languages),
        )
        .where(MovieModel.id == movie_id)
    )
    movie = result.scalar_one_or_none()
    if not movie:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Movie with the given ID was not found."
        )
    return movie


@router.post(
    path="/movies/",
    response_model=MovieDetailSchema,
    status_code=status.HTTP_201_CREATED

)
async def create_movie(
        movie_schema: dict = Body(...),
        db: AsyncSession = Depends(get_db)
):
    try:
        movie_schema = MovieCreateRequestSchema.model_validate(movie_schema)
    except ValidationError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid input data."
        )

    country_result = await db.execute(
        select(CountryModel).where(CountryModel.code == movie_schema.country)
    )
    country = country_result.scalar_one_or_none()
    if not country:
        country = CountryModel(code=movie_schema.country.upper())
        db.add(country)
        await db.flush()

    genres = []
    for genre_name in movie_schema.genres:
        genre_result = await db.execute(
            select(GenreModel).where(GenreModel.name == genre_name)
        )
        genre = genre_result.scalar_one_or_none()
        if not genre:
            genre = GenreModel(name=genre_name)
            db.add(genre)
            await db.flush()
        genres.append(genre)

    actors = []
    for actor_name in movie_schema.actors:
        actor_result = await db.execute(
            select(ActorModel).where(ActorModel.name == actor_name)
        )
        actor = actor_result.scalar_one_or_none()
        if not actor:
            actor = ActorModel(name=actor_name)
            db.add(actor)
            await db.flush()
        actors.append(actor)

    languages = []
    for language_name in movie_schema.languages:
        language_result = await db.execute(
            select(LanguageModel).where(LanguageModel.name == language_name)
        )
        language = language_result.scalar_one_or_none()
        if not language:
            language = LanguageModel(name=language_name)
            db.add(language)
            await db.flush()
        languages.append(language)

    existing_movie_result = await db.execute(
        select(MovieModel)
        .where(
            MovieModel.name == movie_schema.name,
            MovieModel.date == movie_schema.date
        )
    )
    existing_movie = existing_movie_result.scalar_one_or_none()
    if existing_movie:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"A movie with the name '{movie_schema.name}' "
                   f"and release date '{movie_schema.date}' already exists."
        )

    movie = MovieModel(
        name=movie_schema.name,
        date=movie_schema.date,
        score=movie_schema.score,
        overview=movie_schema.overview,
        status=movie_schema.status,
        budget=movie_schema.budget,
        revenue=movie_schema.revenue,
        country_id=country.id,
        genres=genres,
        actors=actors,
        languages=languages
    )

    try:
        db.add(movie)
        await db.commit()
    except IntegrityError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid input data."
        )

    movie = await get_movie_by_id(movie.id, db)
    return MovieDetailSchema.model_validate(movie)


@router.get(
    path="/movies/{movie_id}/",
    response_model=MovieDetailSchema,
    status_code=status.HTTP_200_OK
)
async def get_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    movie = await get_movie_by_id(movie_id, db)
    return MovieDetailSchema.model_validate(movie)


@router.delete(
    path="/movies/{movie_id}/",
    status_code=status.HTTP_204_NO_CONTENT
)
async def delete_movie(movie_id: int, db: AsyncSession = Depends(get_db)):
    movie = await get_movie_by_id(movie_id, db)
    await db.delete(movie)
    await db.commit()


@router.patch(
    path="/movies/{movie_id}/",
    status_code=status.HTTP_200_OK
)
async def partial_update_movie(
    movie_id: int,
    movie_payload: dict = Body(...),
    db: AsyncSession = Depends(get_db)
):
    try:
        movie_schema = MovieUpdateSchema.model_validate(movie_payload)
    except ValidationError:
        raise HTTPException(status_code=400, detail="Invalid input data.")

    movie = await get_movie_by_id(movie_id, db)
    update_data = movie_schema.model_dump(exclude_unset=True)

    for key, value in update_data.items():
        setattr(movie, key, value)
    await db.commit()
    return {"detail": "Movie updated successfully."}
