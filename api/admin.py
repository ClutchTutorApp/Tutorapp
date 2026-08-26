from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import (
    User,
    University,
    Course,
    TutorProfile,
    SessionRequest,
    TutoringSession,
    Payment,
    Review,
    SessionRequestOffer,
    SessionReport,
)


@admin.register(University)
class UniversityAdmin(admin.ModelAdmin):
    list_display = ('id', 'code', 'name', 'created_at')
    search_fields = ('code', 'name')
    ordering = ('code',)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ('id', 'course_key', 'university', 'prefix', 'number', 'created_at')
    list_filter = ('university',)
    search_fields = ('university__code', 'university__name', 'prefix', 'number')
    ordering = ('university__code', 'prefix', 'number')


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    model = User

    list_display = ('id', 'email', 'name', 'role', 'university', 'is_staff', 'created_at')
    list_filter = ('role', 'is_staff', 'is_superuser', 'is_active')
    ordering = ('id',)
    search_fields = ('email', 'name', 'university__code', 'university__name')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('name', 'role', 'university')}),
        (
            'Permissions',
            {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')},
        ),
    )

    add_fieldsets = (
        (
            None,
            {
                'classes': ('wide',),
                'fields': (
                    'email',
                    'name',
                    'role',
                    'university',
                    'password1',
                    'password2',
                    'is_staff',
                    'is_superuser',
                ),
            },
        ),
    )


@admin.register(TutorProfile)
class TutorProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'status', 'last_active_at', 'is_approved', 'rating', 'created_at')
    list_filter = ('status', 'is_approved')
    search_fields = (
        'user__email',
        'user__name',
        'user__university__code',
        'user__university__name',
        'courses_can_teach__prefix',
        'courses_can_teach__number',
    )
    filter_horizontal = ('courses_can_teach',)


@admin.register(SessionRequest)
class SessionRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'student',
        'matched_tutor',
        'course',
        'course_key',
        'mode',
        'status',
        'proposed_price',
        'created_at',
    )
    list_filter = ('status', 'mode', 'course__university')
    search_fields = (
        'student__email',
        'student__name',
        'course__university__code',
        'course__university__name',
        'course__prefix',
        'course__number',
    )


@admin.register(TutoringSession)
class TutoringSessionAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'request',
        'student',
        'tutor',
        'mode',
        'status',
        'final_price',
        'start_time',
        'end_time',
        'created_at',
    )
    list_filter = ('status', 'mode')
    search_fields = (
        'student__email',
        'student__name',
        'tutor__user__email',
        'tutor__user__name',
        'request__course__university__code',
        'request__course__prefix',
        'request__course__number',
    )


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    def duration(self, obj):
        return obj.session.duration_minutes

    duration.short_description = "Duration (min)"

    list_display = (
        'id',
        'session',
        'student',
        'tutor',
        'duration',
        'hourly_rate',
        'total_amount',
        'status',
        'created_at',
    )
    list_filter = ('status', 'created_at')
    search_fields = (
        'student__email',
        'student__name',
        'tutor__user__email',
        'tutor__user__name',
        'session__id',
    )


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'session',
        'student',
        'tutor',
        'rating',
        'created_at',
    )
    list_filter = ('rating', 'created_at')
    search_fields = (
        'student__email',
        'student__name',
        'tutor__user__email',
        'tutor__user__name',
        'comment',
    )


@admin.register(SessionRequestOffer)
class SessionRequestOfferAdmin(admin.ModelAdmin):
    list_display = ('id', 'request', 'tutor', 'status', 'offered_at', 'expires_at', 'responded_at')
    list_filter = ('status',)
    search_fields = ('tutor__user__email', 'request__student__email')


@admin.register(SessionReport)
class SessionReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'session', 'reported_by', 'reason', 'created_at')
    list_filter = ('reason',)
    search_fields = ('session__id', 'reported_by__email')
