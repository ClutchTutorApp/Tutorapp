from rest_framework import serializers
from .models import User, University, Course, TutorProfile, SessionRequest, TutoringSession, Payment, Review
from django.contrib.auth import authenticate


class UniversityCodeField(serializers.SlugRelatedField):
    def to_internal_value(self, data):
        if isinstance(data, str):
            data = University.normalize_code(data)
        return super().to_internal_value(data)


def split_course_code(course_code):
    compact = ''.join(str(course_code).upper().split())
    prefix_chars = []
    number_chars = []
    found_number = False

    for char in compact:
        if not found_number and char.isalpha():
            prefix_chars.append(char)
        else:
            found_number = True
            number_chars.append(char)

    prefix = ''.join(prefix_chars)
    number = ''.join(number_chars)

    if not prefix or not number:
        raise serializers.ValidationError("Course code must look like COP4655.")

    return prefix, number


def get_or_create_course(university_code, prefix, number):
    code = University.normalize_code(university_code)
    prefix = str(prefix).upper().strip()
    number = str(number).strip()

    if not prefix or not number:
        raise serializers.ValidationError("Course prefix and number are required.")

    if len(prefix) > 10:
        raise serializers.ValidationError({"course_prefix": "Course prefix must be 10 characters or fewer."})

    if len(number) > 10:
        raise serializers.ValidationError({"course_number": "Course number must be 10 characters or fewer."})

    try:
        university = University.objects.get(code=code)
    except University.DoesNotExist:
        raise serializers.ValidationError({"university": "Unknown university code."})

    course, _ = Course.objects.get_or_create(
        university=university,
        prefix=prefix,
        number=number,
    )
    return course


class UniversitySerializer(serializers.ModelSerializer):
    class Meta:
        model = University
        fields = ['id', 'name', 'code', 'created_at']
        read_only_fields = ['id', 'created_at']


class CourseSerializer(serializers.ModelSerializer):
    university = UniversityCodeField(slug_field='code', queryset=University.objects.all())
    course_key = serializers.ReadOnlyField()

    class Meta:
        model = Course
        fields = ['id', 'university', 'prefix', 'number', 'course_key', 'created_at']
        read_only_fields = ['id', 'course_key', 'created_at']


class CourseReferenceField(serializers.PrimaryKeyRelatedField):
    def use_pk_only_optimization(self):
        return False

    def to_representation(self, value):
        return CourseSerializer(value).data

    def to_internal_value(self, data):
        if isinstance(data, dict):
            course_id = data.get('id') or data.get('pk')
            if course_id:
                return super().to_internal_value(course_id)

            university = data.get('university') or data.get('university_code')
            prefix = data.get('prefix') or data.get('course_prefix')
            number = data.get('number') or data.get('course_number')

            if not all([university, prefix, number]):
                raise serializers.ValidationError(
                    "Course objects must include university, prefix, and number."
                )

            return get_or_create_course(university, prefix, number)

        if isinstance(data, str):
            value = data.strip()
            if ':' in value:
                university, course_code = value.split(':', 1)
                prefix, number = split_course_code(course_code)
                return get_or_create_course(university, prefix, number)

            if value.isdigit():
                return super().to_internal_value(value)

        return super().to_internal_value(data)


class RegisterSerializer(serializers.ModelSerializer):
    university = UniversityCodeField(slug_field='code', queryset=University.objects.all())
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
    university = UniversityCodeField(slug_field='code', read_only=True)

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
    university = UniversityCodeField(source='user.university', slug_field='code', read_only=True)
    courses_can_teach = CourseReferenceField(
        many=True,
        queryset=Course.objects.select_related('university').all(),
        required=False
    )

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
            'status',
            'last_active_at',
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
            'status',
            'last_active_at',
            'is_approved',
            'created_at',
            'updated_at',
        ]

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
    course = CourseReferenceField(
        queryset=Course.objects.select_related('university').all(),
        required=False
    )
    university = serializers.CharField(required=False)
    course_prefix = serializers.CharField(required=False)
    course_number = serializers.CharField(required=False)
    course_key = serializers.ReadOnlyField()
    matched_tutor_id = serializers.ReadOnlyField(source='matched_tutor.id')
    matched_tutor_name = serializers.ReadOnlyField(source='matched_tutor.user.name')

    class Meta:
        model = SessionRequest
        fields = [
            'id',
            'student_id',
            'student_name',
            'matched_tutor_id',
            'matched_tutor_name',
            'course',
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
        university = data.pop('university', None)
        course_prefix = data.pop('course_prefix', None)
        course_number = data.pop('course_number', None)
        course = data.get('course')

        legacy_fields = [university, course_prefix, course_number]
        provided_legacy_fields = [value for value in legacy_fields if value not in (None, '')]

        if course is None:
            if len(provided_legacy_fields) != 3:
                raise serializers.ValidationError({
                    "course": "Provide course, or provide university, course_prefix, and course_number."
                })

            data['course'] = get_or_create_course(university, course_prefix, course_number)
            return data

        if provided_legacy_fields:
            if len(provided_legacy_fields) != 3:
                raise serializers.ValidationError({
                    "course": "When course is provided, legacy course fields must be omitted or complete."
                })

            legacy_course = get_or_create_course(university, course_prefix, course_number)
            if legacy_course.id != course.id:
                raise serializers.ValidationError({
                    "course": "Course does not match university, course_prefix, and course_number."
                })

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


class PaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = [
            "id",
            "session",
            "student",
            "tutor",
            "hourly_rate",
            "total_amount",
            "status",
            "created_at",
        ]
        read_only_fields = ["student", "tutor", "total_amount", "created_at"]


class CreatePaymentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Payment
        fields = ["session", "hourly_rate", "status"]

    def validate(self, attrs):
        session = attrs["session"]

        if hasattr(session, "payment"):
            raise serializers.ValidationError("This session already has a payment.")

        if not session.duration_minutes:
            raise serializers.ValidationError("Session duration must be set before creating payment.")

        return attrs

class ReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = [
            "id",
            "session",
            "student",
            "tutor",
            "rating",
            "comment",
            "created_at",
        ]
        read_only_fields = ["student", "tutor", "created_at"]

class CreateReviewSerializer(serializers.ModelSerializer):
    class Meta:
        model = Review
        fields = ["session", "rating", "comment"]

    def validate(self, attrs):
        session = attrs["session"]
        request = self.context["request"]

        if hasattr(session, "review"):
            raise serializers.ValidationError("This session already has a review.")

        if request.user != session.student:
            raise serializers.ValidationError("Only the student can leave a review.")

        if session.status not in ["ended", "completed"]:
            raise serializers.ValidationError("You can only review a finished session.")

        return attrs


class TutorStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=TutorProfile.STATUS_CHOICES)
