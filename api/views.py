from rest_framework import generics, status, permissions
from rest_framework.permissions import AllowAny, IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError
from drf_yasg.utils import swagger_auto_schema
from django.utils import timezone
from django.db import transaction
from .daily import create_room, create_meeting_token
import stripe
from django.conf import settings
from django.db import IntegrityError

from .matching import advance_to_next_tutor
from .models import (
    University,
    Course,
    TutorProfile,
    SessionRequest,
    TutoringSession,
    Payment,
    Review,
    SessionRequestOffer,
)
from django.db.models import Q
from .serializers import (
    RegisterSerializer,
    LoginSerializer,
    UserProfileSerializer,
    UniversitySerializer,
    CourseSerializer,
    TutorProfileSerializer,
    SessionRequestSerializer,
    TutoringSessionSerializer,
    PaymentSerializer,
    CreatePaymentSerializer,
    ReviewSerializer,
    CreateReviewSerializer,
    TutorStatusSerializer,
    SessionRequestOfferSerializer,
    SessionReportSerializer,
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
            'university__code', 'prefix', 'number'
        )
        university_code = self.request.query_params.get('university')

        if university_code:
            queryset = queryset.filter(university__code=University.normalize_code(university_code))

        search = self.request.query_params.get('search')

        if search:
            queryset = queryset.filter(Q(prefix__icontains=search) | Q(number__icontains=search))

        return queryset


class RegisterView(generics.CreateAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [AllowAny]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        return Response(
            {"message": "User registered successfully", "user": UserProfileSerializer(user).data},
            status=status.HTTP_201_CREATED,
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
                "user": UserProfileSerializer(user).data,
            },
            status=status.HTTP_200_OK,
        )


class ProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(UserProfileSerializer(request.user).data, status=status.HTTP_200_OK)


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get('refresh')
        if not refresh_token:
            return Response(
                {"error": "Refresh token is required."}, status=status.HTTP_400_BAD_REQUEST
            )
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return Response(
                {"error": "Invalid or already blacklisted token."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({"message": "Logged out successfully."}, status=status.HTTP_200_OK)


class TutorProfileView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'tutor':
            return Response(
                {"error": "Only tutors can access tutor profile data."},
                status=status.HTTP_403_FORBIDDEN,
            )

        tutor_profile, created = TutorProfile.objects.get_or_create(user=request.user)
        serializer = TutorProfileSerializer(tutor_profile)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @swagger_auto_schema(request_body=TutorProfileSerializer)
    def post(self, request):
        if request.user.role != 'tutor':
            return Response(
                {"error": "Only tutors can create or update tutor profiles."},
                status=status.HTTP_403_FORBIDDEN,
            )

        tutor_profile, created = TutorProfile.objects.get_or_create(user=request.user)

        serializer = TutorProfileSerializer(tutor_profile, data=request.data, partial=True)

        if serializer.is_valid():
            serializer.save(user=request.user)
            return Response(serializer.data, status=status.HTTP_200_OK)

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class SessionRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'student':
            return Response(
                {"error": "Only students can view their session requests."},
                status=status.HTTP_403_FORBIDDEN,
            )

        session_requests = SessionRequest.objects.filter(student=request.user).order_by(
            '-created_at'
        )
        serializer = SessionRequestSerializer(session_requests, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    @swagger_auto_schema(request_body=SessionRequestSerializer)
    def post(self, request):
        if not request.user.default_payment_method_id:
            return Response(
                {"error": "Add a payment method before requesting a tutor."},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        if request.user.role != 'student':
            return Response(
                {"error": "Only students can request a tutor."}, status=status.HTTP_403_FORBIDDEN
            )

        serializer = SessionRequestSerializer(data=request.data)

        if serializer.is_valid():
            session_request = serializer.save(student=request.user)
            advance_to_next_tutor(session_request)

            return Response(
                SessionRequestSerializer(session_request).data, status=status.HTTP_201_CREATED
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
                    {"error": "Tutor profile not found."}, status=status.HTTP_404_NOT_FOUND
                )
            sessions = TutoringSession.objects.filter(tutor=tutor_profile).order_by('-created_at')
        else:
            return Response({"error": "Invalid user role."}, status=status.HTTP_403_FORBIDDEN)

        serializer = TutoringSessionSerializer(sessions, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


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

        VALID_TRANSITIONS = {
            'pending': ['active'],
            'active': ['ended'],
            'ended': ['completed', 'disputed'],
        }

        new_status = request.data.get('status')
        if new_status and new_status != session.status:
            allowed = VALID_TRANSITIONS.get(session.status, [])
            if new_status not in allowed:
                return Response(
                    {"error": f"Cannot transition from '{session.status}' to '{new_status}'."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

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
        return Payment.objects.filter(student=user) | Payment.objects.filter(tutor__user=user)


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
        return Payment.objects.filter(tutor__user=user)


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

    def create(self, request, *args, **kwargs):
        try:
            return super().create(request, *args, **kwargs)
        except IntegrityError:
            return Response(
                {"error": "You have already reviewed this session."},
                status=status.HTTP_400_BAD_REQUEST,
            )


class ReviewDetailView(generics.RetrieveAPIView):
    queryset = Review.objects.all()
    serializer_class = ReviewSerializer
    permission_classes = [permissions.IsAuthenticated]
    lookup_url_kwarg = "review_id"


class UpdateTutorStatusView(APIView):
    permission_classes = [IsAuthenticated]

    @swagger_auto_schema(request_body=TutorStatusSerializer)
    def post(self, request):
        if request.user.role != 'tutor':
            return Response(
                {"error": "Only tutors can change status."}, status=status.HTTP_403_FORBIDDEN
            )

        try:
            tutor_profile = request.user.tutor_profile
        except TutorProfile.DoesNotExist:
            return Response({"error": "Tutor profile not found."}, status=status.HTTP_404_NOT_FOUND)

        serializer = TutorStatusSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        if serializer.validated_data['status'] == 'online' and not tutor_profile.stripe_account_id:
            return Response(
                {"error": "Connect a payout account before going online."},
                status=status.HTTP_402_PAYMENT_REQUIRED,
            )

        tutor_profile.status = serializer.validated_data['status']
        update_fields = ['status']

        if tutor_profile.status == 'online':
            tutor_profile.last_active_at = timezone.now()
            update_fields.append('last_active_at')

        tutor_profile.save(update_fields=update_fields)

        return Response(
            {
                "status": tutor_profile.status,
                "last_active_at": tutor_profile.last_active_at,
            },
            status=status.HTTP_200_OK,
        )


class ApproveTutorView(APIView):
    permission_classes = [IsAdminUser]

    def patch(self, request, tutor_id):
        try:
            tutor = TutorProfile.objects.get(id=tutor_id)
        except TutorProfile.DoesNotExist:
            return Response({"error": "Tutor not found."}, status=status.HTTP_404_NOT_FOUND)

        tutor.is_approved = True
        tutor.save(update_fields=['is_approved'])
        return Response({"message": "Tutor approved."}, status=status.HTTP_200_OK)


class CancelSessionRequestView(APIView):
    permission_classes = [IsAuthenticated]

    def patch(self, request, request_id):
        try:
            session_request = SessionRequest.objects.get(id=request_id)
        except SessionRequest.DoesNotExist:
            return Response(
                {"error": "Session request not found."}, status=status.HTTP_404_NOT_FOUND
            )

        if session_request.student != request.user:
            return Response(
                {"error": "You can only cancel your own requests."},
                status=status.HTTP_403_FORBIDDEN,
            )

        if session_request.status not in ['searching', 'matched']:
            return Response(
                {"error": "Only active requests can be cancelled."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        session_request.status = 'cancelled'
        session_request.save(update_fields=['status'])

        return Response({"message": "Session request cancelled."}, status=status.HTTP_200_OK)


class TutorOfferListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        if request.user.role != 'tutor':
            return Response(
                {"error": "Only tutors can view offers."}, status=status.HTTP_403_FORBIDDEN
            )

        try:
            tutor_profile = request.user.tutor_profile
        except TutorProfile.DoesNotExist:
            return Response({"error": "Tutor profile not found."}, status=status.HTTP_404_NOT_FOUND)

        offers = SessionRequestOffer.objects.filter(
            tutor=tutor_profile, status='pending'
        ).select_related('request__course', 'request__student')

        serializer = SessionRequestOfferSerializer(offers, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class AcceptOfferView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, offer_id):
        if request.user.role != 'tutor':
            return Response(
                {"error": "Only tutors can accept offers."}, status=status.HTTP_403_FORBIDDEN
            )

        try:
            tutor_profile = request.user.tutor_profile
        except TutorProfile.DoesNotExist:
            return Response({"error": "Tutor profile not found."}, status=status.HTTP_404_NOT_FOUND)

        with transaction.atomic():
            try:
                offer = SessionRequestOffer.objects.select_for_update().get(
                    id=offer_id, tutor=tutor_profile, status='pending'
                )
            except SessionRequestOffer.DoesNotExist:
                return Response(
                    {"error": "Offer not found or already responded to."},
                    status=status.HTTP_404_NOT_FOUND,
                )

            session_request = offer.request
            if session_request.status != 'searching':
                return Response(
                    {"error": "This request is no longer available."},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            offer.status = 'accepted'
            offer.responded_at = timezone.now()
            offer.save(update_fields=['status', 'responded_at'])

            SessionRequestOffer.objects.filter(request=session_request, status='pending').exclude(
                id=offer.id
            ).update(status='cancelled', responded_at=timezone.now())

            session_request.status = 'matched'
            session_request.matched_tutor = tutor_profile
            session_request.save(update_fields=['status', 'matched_tutor'])

            tutoring_session = TutoringSession.objects.create(
                request=session_request,
                student=session_request.student,
                tutor=tutor_profile,
                mode=session_request.mode,
                status='pending',
                final_price=session_request.proposed_price,
            )

            if session_request.mode == 'remote':
                daily_response = create_room(tutoring_session.id)
                tutoring_session.meeting_link = daily_response['url']
                tutoring_session.room_id = daily_response['name']
                tutoring_session.save(update_fields=['meeting_link', 'room_id'])

        serializer = TutoringSessionSerializer(tutoring_session)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class DeclineOfferView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, offer_id):
        if request.user.role != 'tutor':
            return Response(
                {"error": "Only tutors can decline offers."}, status=status.HTTP_403_FORBIDDEN
            )

        try:
            tutor_profile = request.user.tutor_profile
        except TutorProfile.DoesNotExist:
            return Response({"error": "Tutor profile not found."}, status=status.HTTP_404_NOT_FOUND)

        try:
            offer = SessionRequestOffer.objects.get(
                id=offer_id, tutor=tutor_profile, status='pending'
            )
        except SessionRequestOffer.DoesNotExist:
            return Response(
                {"error": "Offer not found or already responded to."},
                status=status.HTTP_404_NOT_FOUND,
            )

        offer.status = 'declined'
        offer.responded_at = timezone.now()
        offer.save(update_fields=['status', 'responded_at'])

        # Move to next tutor
        advance_to_next_tutor(offer.request)

        return Response({"message": "Offer declined."}, status=status.HTTP_200_OK)


class DisputeSessionView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, session_id):
        try:
            session = TutoringSession.objects.get(id=session_id)
        except TutoringSession.DoesNotExist:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        if request.user != session.student:
            try:
                tutor_profile = request.user.tutor_profile
                if session.tutor != tutor_profile:
                    return Response(
                        {"error": "You are not a participant in this session."},
                        status=status.HTTP_403_FORBIDDEN,
                    )
            except TutorProfile.DoesNotExist:
                return Response(
                    {"error": "You are not a participant in this session."},
                    status=status.HTTP_403_FORBIDDEN,
                )

        serializer = SessionReportSerializer(data=request.data, context={'request': request})
        if serializer.is_valid():
            serializer.save(session=session, reported_by=request.user)
            session.status = 'disputed'
            session.save(update_fields=['status'])
            return Response(
                {"message": "Session disputed successfully."}, status=status.HTTP_201_CREATED
            )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class GetMeetingTokenView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            session = TutoringSession.objects.get(id=session_id)
        except TutoringSession.DoesNotExist:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        if request.user != session.student:
            try:
                tutor_profile = request.user.tutor_profile
                if session.tutor != tutor_profile:
                    return Response(
                        {"error": "Not a participant."}, status=status.HTTP_403_FORBIDDEN
                    )
                is_owner = True
            except TutorProfile.DoesNotExist:
                return Response({"error": "Not a participant."}, status=status.HTTP_403_FORBIDDEN)
        else:
            is_owner = False

        if not session.room_id:
            return Response(
                {"error": "No room created for this session."}, status=status.HTTP_400_BAD_REQUEST
            )

        token_response = create_meeting_token(
            room_name=session.room_id,
            user_name=request.user.name,
            is_owner=is_owner,
        )

        return Response(
            {
                "token": token_response['token'],
                "room_url": session.meeting_link,
            },
            status=status.HTTP_200_OK,
        )


class DailyWebhookView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []

    def post(self, request):
        event_type = request.data.get('type')
        payload = request.data.get('payload', {})
        room_name = payload.get('room', '')

        if not room_name.startswith('clutch-session-'):
            return Response(status=status.HTTP_200_OK)

        try:
            session_id = int(room_name.replace('clutch-session-', ''))
            session = TutoringSession.objects.get(id=session_id)
        except ValueError, TutoringSession.DoesNotExist:
            return Response(status=status.HTTP_200_OK)

        participant = payload.get('participant', {})
        is_owner = participant.get('is_owner', False)
        now = timezone.now()

        if event_type == 'participant-joined':
            update_fields = []

            if is_owner:
                session.tutor_joined_at = now
                update_fields.append('tutor_joined_at')
            else:
                session.student_joined_at = now
                update_fields.append('student_joined_at')

            # Both present — start or resume billing
            if (
                session.student_joined_at
                and session.tutor_joined_at
                and not session.billing_resumed_at
            ):
                session.billing_resumed_at = now
                update_fields.append('billing_resumed_at')
                if not session.start_time:
                    session.start_time = now
                    update_fields.append('start_time')

            session.save(update_fields=update_fields)

        elif event_type == 'participant-left':
            if session.billing_resumed_at:
                elapsed = (now - session.billing_resumed_at).total_seconds()
                session.accumulated_seconds += int(elapsed)
                session.billing_resumed_at = None
                session.save(update_fields=['accumulated_seconds', 'billing_resumed_at'])

        elif event_type == 'meeting-ended':
            update_fields = [
                'end_time',
                'duration_minutes',
                'accumulated_seconds',
                'billing_resumed_at',
            ]
            if session.billing_resumed_at:
                elapsed = (now - session.billing_resumed_at).total_seconds()
                session.accumulated_seconds += int(elapsed)
                session.billing_resumed_at = None
            session.end_time = now
            session.duration_minutes = int(session.accumulated_seconds / 60)
            session.save(update_fields=update_fields)

        return Response(status=status.HTTP_200_OK)


class SessionCostView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, session_id):
        try:
            session = TutoringSession.objects.get(id=session_id)
        except TutoringSession.DoesNotExist:
            return Response({"error": "Session not found."}, status=status.HTTP_404_NOT_FOUND)

        is_participant = request.user == session.student
        if not is_participant:
            try:
                is_participant = session.tutor == request.user.tutor_profile
            except TutorProfile.DoesNotExist:
                pass
        if not is_participant:
            return Response({"error": "Not a participant."}, status=status.HTTP_403_FORBIDDEN)

        now = timezone.now()
        elapsed = session.accumulated_seconds
        is_billing_active = session.billing_resumed_at is not None

        if is_billing_active:
            elapsed += int((now - session.billing_resumed_at).total_seconds())

        hourly_rate = float(session.final_price or 0)
        current_cost = round((elapsed / 3600) * hourly_rate, 2)

        return Response(
            {
                "elapsed_seconds": elapsed,
                "is_billing_active": is_billing_active,
                "hourly_rate": str(session.final_price),
                "current_cost": f"{current_cost:.2f}",
                "student_joined": session.student_joined_at is not None,
                "tutor_joined": session.tutor_joined_at is not None,
            },
            status=status.HTTP_200_OK,
        )


class CreateSetupIntentView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'student':
            return Response(
                {"error": "Only students need payment methods."}, status=status.HTTP_403_FORBIDDEN
            )

        stripe.api_key = settings.STRIPE_SECRET_KEY
        user = request.user

        if not user.stripe_customer_id:
            customer = stripe.Customer.create(
                email=user.email,
                name=user.name,
            )
            user.stripe_customer_id = customer.id
            user.save(update_fields=['stripe_customer_id'])

        setup_intent = stripe.SetupIntent.create(
            customer=user.stripe_customer_id,
            payment_method_types=['card'],
        )

        return Response({"client_secret": setup_intent.client_secret}, status=status.HTTP_200_OK)


class SavePaymentMethodView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        payment_method_id = request.data.get('payment_method_id')
        if not payment_method_id:
            return Response(
                {"error": "payment_method_id required."}, status=status.HTTP_400_BAD_REQUEST
            )

        stripe.api_key = settings.STRIPE_SECRET_KEY
        user = request.user

        stripe.PaymentMethod.attach(payment_method_id, customer=user.stripe_customer_id)
        stripe.Customer.modify(
            user.stripe_customer_id,
            invoice_settings={'default_payment_method': payment_method_id},
        )

        user.default_payment_method_id = payment_method_id
        user.save(update_fields=['default_payment_method_id'])

        return Response({"message": "Payment method saved."}, status=status.HTTP_200_OK)


class TutorConnectView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if request.user.role != 'tutor':
            return Response(
                {"error": "Only tutors can connect a payout account."},
                status=status.HTTP_403_FORBIDDEN,
            )

        try:
            tutor_profile = request.user.tutor_profile
        except TutorProfile.DoesNotExist:
            return Response({"error": "Tutor profile not found."}, status=status.HTTP_404_NOT_FOUND)

        stripe.api_key = settings.STRIPE_SECRET_KEY

        if not tutor_profile.stripe_account_id:
            account = stripe.Account.create(
                type='express',
                email=request.user.email,
                capabilities={
                    'transfers': {'requested': True},
                },
            )
            tutor_profile.stripe_account_id = account.id
            tutor_profile.save(update_fields=['stripe_account_id'])

        link = stripe.AccountLink.create(
            account=tutor_profile.stripe_account_id,
            refresh_url='https://clutchtutorapp.com/connect/refresh/',
            return_url='https://clutchtutorapp.com/connect/return/',
            type='account_onboarding',
        )

        return Response({"onboarding_url": link.url}, status=status.HTTP_200_OK)


class SessionRequestDetailView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, request_id):
        try:
            session_request = SessionRequest.objects.get(id=request_id)
        except SessionRequest.DoesNotExist:
            return Response(
                {"error": "Session request not found."}, status=status.HTTP_404_NOT_FOUND
            )

        if session_request.student != request.user:
            return Response(
                {"error": "You can only view your own session requests."},
                status=status.HTTP_403_FORBIDDEN,
            )

        serializer = SessionRequestSerializer(session_request)
        return Response(serializer.data, status=status.HTTP_200_OK)
