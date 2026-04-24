from rest_framework import generics, status, permissions
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from drf_yasg.utils import swagger_auto_schema

from .models import University, Course, TutorProfile, SessionRequest, TutoringSession, Payment, Review
from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    UserProfileSerializer,
    UniversitySerializer,
    CourseSerializer,
    TutorProfileSerializer,
    SessionRequestSerializer,
    TutoringSessionSerializer,
    CreateTutoringSessionSerializer,
    PaymentSerializer,
    CreatePaymentSerializer,
    ReviewSerializer,
    CreateReviewSerializer,
)


class UniversityListView(generics.ListAPIView):
    queryset = University.objects.all().order_by('code')
    serializer_class = UniversitySerializer
    permission_classes = [AllowAny]


class CourseListView(generics.ListAPIView):
    serializer_class = CourseSerializer
    permission_classes = [AllowAny]

    def get_queryset(self):
        queryset = Course.objects.select_related('university').order_by(
            'university__code',
            'prefix',
            'number'
        )
        university_code = self.request.query_params.get('university')

        if university_code:
            queryset = queryset.filter(
                university__code=University.normalize_code(university_code)
            )

        return queryset


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        return Response(
            {
                "message": "User registered successfully",
                "user": UserProfileSerializer(user).data
            },
            status=status.HTTP_201_CREATED
        )


class LoginView(APIView):
    permission_classes = [AllowAny]

    @swagger_auto_schema(request_body=LoginSerializer)
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user = serializer.validated_data['user']
        refresh = RefreshToken.for_user(user)

        return Response(
            {
                "message": "Login successful",
                "access": str(refresh.access_token),
                "refresh": str(refresh),
                "user": UserProfileSerializer(user).data
            },
            status=status.HTTP_200_OK
        )


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserProfileSerializer(request.user).data, status=status.HTTP_200_OK)


class TutorProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'tutor':
            return Response(
                {"error": "Only tutors can access tutor profile data."},
                status=status.HTTP_403_FORBIDDEN
            )

        tutor_profile, created = TutorProfile.objects.get_or_create(user=request.user)
        serializer = TutorProfileSerializer(tutor_profile)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @swagger_auto_schema(request_body=TutorProfileSerializer)
    def post(self, request):
        if request.user.role != 'tutor':
            return Response(
                {"error": "Only tutors can create or update tutor profiles."},
                status=status.HTTP_403_FORBIDDEN
            )

        tutor_profile, created = TutorProfile.objects.get_or_create(user=request.user)

        serializer = TutorProfileSerializer(
            tutor_profile,
            data=request.data,
            partial=True
        )

        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class SessionRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def find_matching_tutor(self, session_request):
        return (
            TutorProfile.objects
            .select_related('user')
            .filter(
                courses_can_teach=session_request.course,
                is_approved=True,
                user__role='tutor',
            )
            .exclude(user=session_request.student)
            .order_by('-is_online', '-rating', 'created_at')
            .first()
        )

    def get(self, request):
        if request.user.role != 'student':
            return Response(
                {"error": "Only students can view their session requests."},
                status=status.HTTP_403_FORBIDDEN
            )

        session_requests = SessionRequest.objects.filter(student=request.user).order_by('-created_at')
        serializer = SessionRequestSerializer(session_requests, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @swagger_auto_schema(request_body=SessionRequestSerializer)
    def post(self, request):
        if request.user.role != 'student':
            return Response(
                {"error": "Only students can create session requests."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = SessionRequestSerializer(data=request.data)

        if serializer.is_valid():
            session_request = serializer.save(student=request.user)
            matched_tutor = self.find_matching_tutor(session_request)

            if matched_tutor:
                session_request.matched_tutor = matched_tutor
                session_request.status = 'matched'
                session_request.save(update_fields=['matched_tutor', 'status'])

            return Response(
                SessionRequestSerializer(session_request).data,
                status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class TutoringSessionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role == 'student':
            sessions = TutoringSession.objects.filter(student=request.user).order_by('-created_at')
        elif request.user.role == 'tutor':
            try:
                tutor_profile = request.user.tutor_profile
            except TutorProfile.DoesNotExist:
                return Response(
                    {"error": "Tutor profile not found."},
                    status=status.HTTP_404_NOT_FOUND
                )
            sessions = TutoringSession.objects.filter(tutor=tutor_profile).order_by('-created_at')
        else:
            return Response(
                {"error": "Invalid user role."},
                status=status.HTTP_403_FORBIDDEN
            )

        serializer = TutoringSessionSerializer(sessions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

class CreateTutoringSessionView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(request_body=CreateTutoringSessionSerializer)
    def post(self, request):
        if request.user.role != 'tutor':
            return Response(
                {"error": "Only tutors can create tutoring sessions."},
                status=status.HTTP_403_FORBIDDEN
            )

        try:
            tutor_profile = request.user.tutor_profile
        except TutorProfile.DoesNotExist:
            return Response(
                {"error": "Tutor profile not found."},
                status=status.HTTP_404_NOT_FOUND
            )

        serializer = CreateTutoringSessionSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session_request = serializer.validated_data['session_request']

        if session_request.matched_tutor != tutor_profile:
            return Response(
                {"error": "You are not the matched tutor for this request."},
                status=status.HTTP_403_FORBIDDEN
            )

        tutoring_session = TutoringSession.objects.create(
            request=session_request,
            student=session_request.student,
            tutor=tutor_profile,
            mode=session_request.mode,
            status='pending',
            final_price=session_request.proposed_price,
            meeting_link=serializer.validated_data.get('meeting_link', ''),
            room_id=serializer.validated_data.get('room_id', ''),
        )

        return Response(
            TutoringSessionSerializer(tutoring_session).data,
            status=status.HTTP_201_CREATED
        )

class TutoringSessionDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get_object(self, session_id, user):
        try:
            session = TutoringSession.objects.get(id=session_id)
        except TutoringSession.DoesNotExist:
            return None

        if user.role == 'student' and session.student == user:
            return session

        if user.role == 'tutor':
            try:
                tutor_profile = user.tutor_profile
            except TutorProfile.DoesNotExist:
                return None

            if session.tutor == tutor_profile:
                return session

        return None

    def get(self, request, session_id):
        session = self.get_object(session_id, request.user)
        if not session:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TutoringSessionSerializer(session)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @swagger_auto_schema(request_body=TutoringSessionSerializer)
    def patch(self, request, session_id):
        session = self.get_object(session_id, request.user)
        if not session:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TutoringSessionSerializer(session, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class PaymentListView(generics.ListAPIView):
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Payment.objects.filter(student=user) | Payment.objects.filter(tutor=user)


class PaymentCreateView(generics.CreateAPIView):
    queryset = Payment.objects.all()
    serializer_class = CreatePaymentSerializer
    permission_classes = [permissions.IsAuthenticated]


class PaymentDetailView(generics.RetrieveAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_url_kwarg = "payment_id"


class PaymentUpdateView(generics.UpdateAPIView):
    queryset = Payment.objects.all()
    serializer_class = PaymentSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_url_kwarg = "payment_id"
    http_method_names = ["patch"]

    def get_queryset(self):
        user = self.request.user
        return Payment.objects.filter(tutor=user)


class ReviewListView(generics.ListAPIView):
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        return Review.objects.filter(student=user) | Review.objects.filter(tutor__user=user)

class ReviewCreateView(generics.CreateAPIView):
    queryset = Review.objects.all()
    serializer_class = CreateReviewSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["request"] = self.request
        return context

class ReviewDetailView(generics.RetrieveAPIView):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_url_kwarg = "review_id"
