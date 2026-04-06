from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    RegisterView,
    LoginView,
    ProfileView,
    TutorProfileView,
    SessionRequestView,
    TutoringSessionListView,
    CreateTutoringSessionView,
    TutoringSessionDetailView,
)

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),
    path('profile/', ProfileView.as_view(), name='profile'),
    path('tutor-profile/', TutorProfileView.as_view(), name='tutor_profile'),
    path('session-requests/', SessionRequestView.as_view(), name='session_requests'),
    path('sessions/', TutoringSessionListView.as_view(), name='tutoring_sessions'),
    path('sessions/create/', CreateTutoringSessionView.as_view(), name='create_tutoring_session'),
    path('sessions/<int:session_id>/', TutoringSessionDetailView.as_view(), name='tutoring_session_detail'),
]