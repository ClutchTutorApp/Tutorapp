from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from decimal import Decimal
from django.conf import settings
from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

class UserManager(BaseUserManager):
    def create_user(self, email, name, role, university, password=None, **extra_fields):
        if not email:
            raise ValueError("Users must have an email address")

        email = self.normalize_email(email)

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


class User(AbstractBaseUser, PermissionsMixin):
    ROLE_CHOICES = (
        ('student', 'Student'),
        ('tutor', 'Tutor'),
    )

    email = models.EmailField(unique=True)
    name = models.CharField(max_length=255)
    role = models.CharField(max_length=20, choices=ROLE_CHOICES)
    university = models.CharField(max_length=255)
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
    courses_can_teach = models.JSONField(default=list, blank=True)
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
    university = models.CharField(max_length=20)
    course_prefix = models.CharField(max_length=10)
    course_number = models.CharField(max_length=10)
    course_key = models.CharField(max_length=50, db_index=True)
    mode = models.CharField(max_length=20, choices=MODE_CHOICES)
    description = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='searching')
    proposed_price = models.DecimalField(max_digits=8, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        self.university = self.university.upper().strip()
        self.course_prefix = self.course_prefix.upper().strip()
        self.course_number = self.course_number.strip()
        self.course_key = f"{self.university}:{self.course_prefix}{self.course_number}"
        super().save(*args, **kwargs)

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