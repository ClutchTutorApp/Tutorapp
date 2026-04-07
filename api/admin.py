from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from .models import User, TutorProfile, SessionRequest, TutoringSession, Payment, Review


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    model = User

    list_display = ('id', 'email', 'name', 'role', 'university', 'is_staff', 'created_at')
    list_filter = ('role', 'is_staff', 'is_superuser', 'is_active')
    ordering = ('id',)
    search_fields = ('email', 'name', 'university')

    fieldsets = (
        (None, {'fields': ('email', 'password')}),
        ('Personal Info', {'fields': ('name', 'role', 'university')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'name', 'role', 'university', 'password1', 'password2', 'is_staff', 'is_superuser'),
        }),
    )


@admin.register(TutorProfile)
class TutorProfileAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'is_online', 'is_approved', 'rating', 'created_at')
    list_filter = ('is_online', 'is_approved')
    search_fields = ('user__email', 'user__name', 'user__university')


@admin.register(SessionRequest)
class SessionRequestAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'student',
        'matched_tutor',
        'course_key',
        'mode',
        'status',
        'proposed_price',
        'created_at',
    )
    list_filter = ('status', 'mode', 'university')
    search_fields = ('student__email', 'student__name', 'course_key')


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
        'request__course_key',
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