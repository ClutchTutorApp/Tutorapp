from datetime import timedelta
from decimal import Decimal

from django.db.models import Count
from django.utils import timezone

from .models import SessionRequestOffer, TutorProfile

INACTIVITY_LIMIT = timedelta(minutes=10)
OFFER_TTL = timedelta(seconds=60)

# Each tutor gets phantom prior reviews so brand-new tutors aren't buried.
# A tutor with 0 real reviews has effective rating == PRIOR_RATING (4.0).
PRIOR_REVIEWS = 3
PRIOR_RATING = Decimal("4.0")


def _bayesian_score(rating, review_count):
    rating = Decimal(rating or 0)
    return (rating * review_count + PRIOR_RATING * PRIOR_REVIEWS) / (review_count + PRIOR_REVIEWS)


def _eligible_tutors(session_request):
    cutoff = timezone.now() - INACTIVITY_LIMIT
    return (
        TutorProfile.objects
        .annotate(review_count=Count("reviews_received"))
        .filter(
            courses_can_teach=session_request.course,
            is_approved=True,
            user__role="tutor",
            status="online",
            last_active_at__gte=cutoff,
        )
        .exclude(
            user=session_request.student
        )
        .exclude(
            offers_received__status='pending'
        )
    )


def _rank(tutors):
    scored = [(_bayesian_score(t.rating, t.review_count), t.created_at, t) for t in tutors]
    # higher score first; among ties, older accounts first (fairness)
    scored.sort(key=lambda x: (-x[0], x[1]))
    return [t for _, _, t in scored]


def _next_tutor(session_request):
    already_offered = session_request.offers.values_list("tutor_id", flat=True)
    candidates = _eligible_tutors(session_request).exclude(id__in=already_offered)
    ranked = _rank(candidates)
    return ranked[0] if ranked else None


def _expire_stale_offers(session_request):
    now = timezone.now()
    SessionRequestOffer.objects.filter(
        request=session_request,
        status="pending",
        expires_at__lte=now,
    ).update(status="expired", responded_at=now)


def advance_to_next_tutor(session_request):
    """
    Idempotent: call this whenever something might have changed.
    - Expires stale pending offers.
    - If no live pending offer, sends one to the next eligible tutor.
    - If no eligible tutors remain, marks the request as expired.
    Returns the new SessionRequestOffer, or None.
    """
    if session_request.status != "searching":
        return None

    _expire_stale_offers(session_request)

    if session_request.offers.filter(status="pending").exists():
        return None  # someone still has a live offer, wait it out

    tutor = _next_tutor(session_request)
    if tutor is None:
        session_request.status = "expired"
        session_request.save(update_fields=["status"])
        return None

    return SessionRequestOffer.objects.create(
        request=session_request,
        tutor=tutor,
        expires_at=timezone.now() + OFFER_TTL,
    )