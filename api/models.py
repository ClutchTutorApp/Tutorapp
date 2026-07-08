from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from decimal import Decimal
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db.models import Avg
import stripe

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
    stripe_customer_id = models.CharField(max_length=255, blank=True, null=True)
    default_payment_method_id = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)

    objects = UserManager()

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name', 'role', 'university']

    def __str__(self):
        return self.email

class TutorProfile(models.Model):
    STATUS_CHOICES = (
        ('offline', 'Offline'),
        ('online', 'Online'),
        ('busy', 'Busy'),
        ('in_session', 'In_session'),
    )

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
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='offline')
    last_active_at = models.DateTimeField(null=True, blank=True)
    is_approved = models.BooleanField(default=False)
    stripe_account_id = models.CharField(max_length=255, blank=True, null=True)
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
    student_joined_at = models.DateTimeField(null=True, blank=True)
    tutor_joined_at = models.DateTimeField(null=True, blank=True)
    accumulated_seconds = models.PositiveIntegerField(default=0)
    billing_resumed_at = models.DateTimeField(null=True, blank=True)

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
        ("failed", "Failed"),
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
    stripe_payment_intent_id = models.CharField(max_length=255, blank=True, null=True)
    platform_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0)
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

@receiver(post_save, sender=Review)
def update_tutor_rating(sender, instance, **kwargs):
    tutor = instance.tutor
    recent_ids = Review.objects.filter(tutor=tutor).order_by('-created_at').values_list('id', flat=True)[:100]
    avg = Review.objects.filter(id__in=recent_ids).aggregate(Avg('rating'))['rating__avg']
    tutor.rating = avg or Decimal("4.0")
    tutor.save(update_fields=['rating'])


class SessionRequestOffer(models.Model):
    STATUS_CHOICES = (
        ("pending", "Pending"),
        ("accepted", "Accepted"),
        ("declined", "Declined"),
        ("expired", "Expired"),
        ("cancelled", "Cancelled"),  # superseded by another tutor accepting or student cancelling
    )

    request = models.ForeignKey(
        SessionRequest,
        on_delete=models.CASCADE,
        related_name="offers",
    )
    tutor = models.ForeignKey(
        TutorProfile,
        on_delete=models.CASCADE,
        related_name="offers_received",
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="pending")
    offered_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["offered_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["request", "tutor"],
                name="unique_offer_per_tutor_per_request",
            )
        ]

    def __str__(self):
        return f"Offer #{self.id} - {self.tutor.user.email} - {self.status}"

class SessionReport(models.Model):
    REASON_CHOICES = (
        ('tutor_no_show', 'Tutor did not show up'),
        ('student_no_show', 'Student did not show up'),
        ('poor_quality', 'Session quality was poor'),
        ('technical_issue', 'Technical issues prevented the session'),
        ('payment_dispute', 'Dispute over payment amount'),
        ('other', 'Other'),
    )

    session = models.OneToOneField(TutoringSession, on_delete=models.CASCADE, related_name='report')
    reported_by = models.ForeignKey(User, on_delete=models.CASCADE)
    reason = models.CharField(max_length=50, choices=REASON_CHOICES)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Report #{self.id} - Session {self.session.id} - {self.reason}"


@receiver(post_save, sender=TutoringSession)
def auto_create_payment(sender, instance, created, **kwargs):
    if instance.status != 'ended':
        return
    if Payment.objects.filter(session=instance).exists():
        return

    hourly_rate = float(instance.final_price or 0)
    duration_hours = (instance.duration_minutes or 0) / 60
    total_amount = round(hourly_rate * duration_hours, 2)

    if total_amount <= 0:
        return

    platform_fee = round(total_amount * settings.PLATFORM_FEE_PERCENT, 2)

    stripe.api_key = settings.STRIPE_SECRET_KEY

    try:
        intent = stripe.PaymentIntent.create(
            amount=int(total_amount * 100),  # Stripe uses cents
            currency='usd',
            customer=instance.student.stripe_customer_id,
            payment_method=instance.student.default_payment_method_id,
            confirm=True,
            off_session=True,
            transfer_data={'destination': instance.tutor.stripe_account_id},
            application_fee_amount=int(platform_fee * 100),
        )
        pay_status = 'held'
        intent_id = intent.id

    except stripe.error.CardError:
        pay_status = 'failed'
        intent_id = None

    Payment.objects.create(
        session=instance,
        student=instance.student,
        tutor=instance.tutor,
        hourly_rate=instance.final_price,
        total_amount=total_amount,
        platform_fee=platform_fee,
        stripe_payment_intent_id=intent_id,
        status=pay_status,
    )