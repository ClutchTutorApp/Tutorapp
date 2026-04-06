from rest_framework import serializers
from .models import User, TutorProfile, SessionRequest, TutoringSession
from django.contrib.auth import authenticate


class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)
    password_confirm = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['id', 'email', 'name', 'role', 'university', 'password', 'password_confirm', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password": "Passwords do not match."})
        return attrs

    def create(self, validated_data):
        validated_data.pop('password_confirm')

        user = User.objects.create_user(
            email=validated_data['email'],
            name=validated_data['name'],
            role=validated_data['role'],
            university=validated_data['university'],
            password=validated_data['password']
        )
        return user


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, attrs):
        email = attrs.get('email')
        password = attrs.get('password')

        user = authenticate(username=email, password=password)

        if not user:
            raise serializers.ValidationError("Invalid email or password.")

        if not user.is_active:
            raise serializers.ValidationError("This account is disabled.")

        attrs['user'] = user
        return attrs

class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = [
            'id',
            'email',
            'name',
            'role',
            'university',
            'created_at',
        ]


class TutorProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.ReadOnlyField(source='user.id')
    name = serializers.ReadOnlyField(source='user.name')
    email = serializers.ReadOnlyField(source='user.email')
    university = serializers.ReadOnlyField(source='user.university')

    class Meta:
        model = TutorProfile
        fields = [
            'id',
            'user_id',
            'name',
            'email',
            'university',
            'courses_can_teach',
            'general_topics',
            'bio',
            'rating',
            'is_online',
            'payout_info_placeholder',
            'is_approved',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'user_id',
            'name',
            'email',
            'university',
            'rating',
            'is_approved',
            'created_at',
            'updated_at',
        ]

    def validate_courses_can_teach(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("courses_can_teach must be a list.")
        for item in value:
            if not isinstance(item, str):
                raise serializers.ValidationError("Each course must be a string.")
        return value

    def validate_general_topics(self, value):
        if not isinstance(value, list):
            raise serializers.ValidationError("general_topics must be a list.")
        for item in value:
            if not isinstance(item, str):
                raise serializers.ValidationError("Each topic must be a string.")
        return value

class SessionRequestSerializer(serializers.ModelSerializer):
    student_id = serializers.ReadOnlyField(source='student.id')
    student_name = serializers.ReadOnlyField(source='student.name')
    course_key = serializers.ReadOnlyField()
    matched_tutor_id = serializers.ReadOnlyField(source='matched_tutor.id')
    matched_tutor_name = serializers.ReadOnlyField(source='matched_tutor.user.name')

    VALID_UNIVERSITIES = ['FAU', 'UF', 'UCF']

    class Meta:
        model = SessionRequest
        fields = [
            'id',
            'student_id',
            'student_name',
            'matched_tutor_id',
            'matched_tutor_name',
            'university',
            'course_prefix',
            'course_number',
            'course_key',
            'mode',
            'description',
            'status',
            'proposed_price',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'student_id',
            'student_name',
            'matched_tutor_id',
            'matched_tutor_name',
            'course_key',
            'status',
            'created_at',
        ]

    def validate(self, data):
        university = data['university'].upper().strip()
        course_prefix = data['course_prefix'].upper().strip()
        course_number = data['course_number'].strip()

        if university not in self.VALID_UNIVERSITIES:
            raise serializers.ValidationError({
                "university": f"University must be one of: {', '.join(self.VALID_UNIVERSITIES)}"
            })

        data['university'] = university
        data['course_prefix'] = course_prefix
        data['course_number'] = course_number

        return data

class TutoringSessionSerializer(serializers.ModelSerializer):
    request_id = serializers.ReadOnlyField(source='request.id')
    student_id = serializers.ReadOnlyField(source='student.id')
    student_name = serializers.ReadOnlyField(source='student.name')
    tutor_id = serializers.ReadOnlyField(source='tutor.id')
    tutor_name = serializers.ReadOnlyField(source='tutor.user.name')
    course_key = serializers.ReadOnlyField(source='request.course_key')

    class Meta:
        model = TutoringSession
        fields = [
            'id',
            'request_id',
            'student_id',
            'student_name',
            'tutor_id',
            'tutor_name',
            'course_key',
            'mode',
            'status',
            'start_time',
            'end_time',
            'duration_minutes',
            'final_price',
            'meeting_link',
            'room_id',
            'created_at',
        ]
        read_only_fields = [
            'id',
            'request_id',
            'student_id',
            'student_name',
            'tutor_id',
            'tutor_name',
            'course_key',
            'duration_minutes',
            'created_at',
        ]


class CreateTutoringSessionSerializer(serializers.Serializer):
    request_id = serializers.IntegerField()
    meeting_link = serializers.URLField(required=False, allow_blank=True)
    room_id = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        request_id = attrs.get('request_id')

        try:
            session_request = SessionRequest.objects.get(id=request_id)
        except SessionRequest.DoesNotExist:
            raise serializers.ValidationError({"request_id": "SessionRequest not found."})

        if session_request.status != 'matched':
            raise serializers.ValidationError({"request_id": "Only matched requests can become tutoring sessions."})

        if session_request.matched_tutor is None:
            raise serializers.ValidationError({"request_id": "This request does not have a matched tutor."})

        if hasattr(session_request, 'tutoring_session'):
            raise serializers.ValidationError({"request_id": "A tutoring session already exists for this request."})

        attrs['session_request'] = session_request
        return attrs