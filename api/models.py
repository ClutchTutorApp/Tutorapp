from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator

class UserManager(BaseUserManager):
    def _resolve_university(self, university):
        if isinstance(university, University):
            return university

        if university is None:
            raise ValueError("Users must have a university")

        if isinstance(university, int):
            return University.objects.get(id=university)

        raw_value = str(university).strip()
        if not raw_value:
            raise ValueError("Users must have a university")

        code = University.normalize_code(raw_value)
        university_obj, _ = University.objects.get_or_create(
            code=code,
            defaults={"name": raw_value},
        )
        return university_obj

    def create_user(self, email, name, role, university, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")

        email = self.normalize_email(email)
        university = self._resolve_university(university)

        user = self.model(
            email=email,
            name=name,
            role=role,
            university=university,
            **extra_fields
        )

        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, email, name, role='student', university='Admin University', password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)

        return self.create_user(
            email=email,
            name=name,
            role=role,
            university=university,
            password=password,
            **extra_fields
        )


class University(models.Model):
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=10, unique=True)  # e.g. FAU, UF
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['code']

    @staticmethod
    def normalize_code(value):
        text = str(value).strip()
        compact = ''.join(char for char in text.upper() if char.isalnum())
        if not compact:
            return 'UNKNOWN'
        if len(compact) <= 10:
            return compact

        words = ''.join(char if char.isalnum() else ' ' for char in text).split()
        initials = ''.join(word[0] for word in words).upper()
        if 1 < len(initials) <= 10:
            return initials

        return compact[:10]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.code = self.normalize_code(self.code)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.code


class Course(models.Model):
    university = models.ForeignKey(
        University,
        on_delete=models.CASCADE,
        related_name='courses'
    )
    prefix = models.CharField(max_length=10)   # COP
    number = models.CharField(max_length=10)   # 4655
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['university__code', 'prefix', 'number']
        constraints = [
            models.UniqueConstraint(
                fields=['university', 'prefix', 'number'],
                name='unique_course_per_university'
            )
        ]

    @property
    def course_key(self):
        return f"{self.university.code}:{self.prefix}{self.number}"

    def save(self, *args, **kwargs):
        self.prefix = self.prefix.upper().strip()
        self.number = self.number.strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return self.course_key

class User(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = (
        ('student', 'Student'),
        ('tutor', 'Tutor'),
    )

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    university = models.ForeignKey(
        University,
        on_delete=models.CASCADE,
        related_name='users'
    )
    created_at = models.DateTimeField(auto_now_add=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name', 'role', 'university']

    def __str__(self):
        return self.email

class TutorProfile(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='tutor_profile'
    )
    courses_can_teach = models.ManyToManyField(
        Course,
        blank=True,
        related_name='tutor_profiles'
    )
    general_topics = models.JSONField(default=list, blank=True)
    bio = models.TextField(blank=True)
    rating = models.DecimalField(max_digits=3, decimal_places=2, default=0.00)
    is_online = models.BooleanField(default=False)
    payout_info_placeholder = models.CharField(max_length=255, blank=True, default='')
    is_approved = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def save(self, *args, **kwargs):
        if self.user.role != 'tutor':
            raise ValueError("TutorProfile can only be created for users with role='tutor'")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"TutorProfile - {self.user.email}"

class SessionRequest(models.Model):
    STATUS_CHOICES = (
        ('searching', 'Searching'),
        ('matched', 'Matched'),
        ('cancelled', 'Cancelled'),
        ('expired', 'Expired'),
    )

    MODE_CHOICES = (
        ('remote', 'Remote'),
        ('in_person', 'In Person'),
    )

    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='session_requests'
    )
    matched_tutor = models.ForeignKey(
        TutorProfile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='matched_session_requests'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='session_requests'
    )
    mode = models.CharField(max_length=20, choices=MODE_CHOICES, default="remote")
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='searching')
    proposed_price = models.DecimalField(max_digits=8, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def university(self):
        return self.course.university.code

    @property
    def course_prefix(self):
        return self.course.prefix

    @property
    def course_number(self):
        return self.course.number

    @property
    def course_key(self):
        return self.course.course_key

    def __str__(self):
        return f"{self.student.email} - {self.course_key} - {self.status}"

class TutoringSession(models.Model):
    STATUS_CHOICES = (
        ('pending', 'Pending'),
        ('active', 'Active'),
        ('ended', 'Ended'),
        ('completed', 'Completed'),
        ('disputed', 'Disputed'),
    )

    request = models.OneToOneField(
        SessionRequest,
        on_delete=models.CASCADE,
        related_name='tutoring_session'
    )
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='student_tutoring_sessions'
    )
    tutor = models.ForeignKey(
        TutorProfile,
        on_delete=models.CASCADE,
        related_name='tutor_tutoring_sessions'
    )
    mode = models.CharField(max_length=20, choices=SessionRequest.MODE_CHOICES)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    start_time = models.DateTimeField(null=True, blank=True)
    end_time = models.DateTimeField(null=True, blank=True)
    duration_minutes = models.PositiveIntegerField(null=True, blank=True)
    final_price = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    meeting_link = models.URLField(blank=True, default='')
    room_id = models.CharField(max_length=255, blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            self.duration_minutes = max(int(delta.total_seconds() // 60), 0)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Session #{self.id} - {self.request.course_key} - {self.status}"


class Payment(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("held", "Held"),
        ("released", "Released"),
        ("refunded", "Refunded"),
    ]

    session = models.OneToOneField(
        "TutoringSession",
        on_delete=models.CASCADE,
        related_name="payment"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="payments_made"
    )
    tutor = models.ForeignKey(
        "TutorProfile",
        on_delete=models.CASCADE,
        related_name="payments_received"
    )
    hourly_rate = models.DecimalField(max_digits=8, decimal_places=2)
    total_amount = models.DecimalField(max_digits=8, decimal_places=2, default=Decimal("0.00"))
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(auto_now_add=True)

    def calculate_total(self):
        if self.session.duration_minutes:
            hours = Decimal(str(self.session.duration_minutes)) / Decimal("60")
            return self.hourly_rate * hours
        return Decimal("0.00")

    def save(self, *args, **kwargs):
        self.student = self.session.student
        self.tutor = self.session.tutor
        self.total_amount = self.calculate_total()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Payment #{self.id} - Session {self.session.id}"


class Review(models.Model):
    session = models.OneToOneField(
        "TutoringSession",
        on_delete=models.CASCADE,
        related_name="review"
    )
    student = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="reviews_given"
    )
    tutor = models.ForeignKey(
        "TutorProfile",
        on_delete=models.CASCADE,
        related_name="reviews_received"
    )
    rating = models.PositiveIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.student = self.session.student
        self.tutor = self.session.tutor
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Review #{self.id} - Session {self.session.id}"
