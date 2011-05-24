from django.db import models
from django.utils.translation import gettext as _
from django.core.urlresolvers import reverse
from django.core.exceptions import ValidationError
from django.conf import settings

from oscar.apps.product.reviews.managers import (ApprovedReviewsManager, RecentReviewsManager, 
                                                 TopScoredReviewsManager, TopVotedReviewsManager)


class AbstractProductReview(models.Model):
    """
    Superclass ProductReview. Some key aspects have been implemented from the original spec.
    * Each product can have reviews attached to it. Each review has a title, a body and a score from 1-5.
    * Signed in users can always submit reviews, anonymous users can only submit reviews if a setting
      OSCAR_ALLOW_ANON_REVIEWS is set to true - it should default to false.
    * If anon users can submit reviews, then we require their name, email address and an (optional) URL.
    * By default, reviews must be approved before they are live.
      However, if a setting OSCAR_MODERATE_REVIEWS is set to false, then they don't need moderation.
    * Each review should have a permalink, ie it has its own page.
    * Each reviews can be voted up or down by other users
    * Only signed in users can vote
    * A user can only vote once on each product once
    """
    
    # Note we keep the review even if the product is deleted
    product = models.ForeignKey('product.Item', related_name='product', null=True, on_delete=models.SET_NULL)
    
    SCORE_CHOICES = tuple([(x, x) for x in range(0, 6)])
    score = models.SmallIntegerField(_("Score"), choices=SCORE_CHOICES)
    title = models.CharField(_("Title"), max_length=255)
    body = models.TextField(_("Body"))
    
    # User information.  We include fields to handle anonymous users
    user = models.ForeignKey('auth.User', related_name='reviews', null=True, blank=True)
    name = models.CharField(_("Name"), max_length=255, null=True, blank=True)
    email = models.EmailField(_("Email"), null=True, blank=True)
    homepage = models.URLField(_("URL"), null=True, blank=True)
    
    FOR_MODERATION, APPROVED, REJECTED = range(0, 3)
    STATUS_CHOICES = (
        (FOR_MODERATION, _("Requires moderation")),
        (APPROVED, _("Approved")),
        (REJECTED, _("Rejected")), 
    ) 
    default_status = FOR_MODERATION if settings.OSCAR_MODERATE_REVIEWS else APPROVED
    status = models.SmallIntegerField(_("Status"), choices=STATUS_CHOICES, default=default_status)
    
    # Denormalised vote totals
    total_votes = models.IntegerField(_("Total Votes"), default=0)  # upvotes + down votes
    delta_votes = models.IntegerField(_("Delta Votes"), default=0, db_index=True)  # upvotes - down votes  
    
    date_created = models.DateTimeField(auto_now_add=True)
    
    # Managers
    objects = models.Manager()
    approved = ApprovedReviewsManager()

    class Meta:
        abstract = True
        ordering = ['-delta_votes']
        unique_together = (('product', 'user'),)

    @models.permalink
    def get_absolute_url(self):
        return ('oscar-product-review', (), {
            'item_class_slug': self.product.get_item_class().slug,
            'item_slug': self.product.slug,
            'item_id': self.product.id,
            'pk': self.id})

    def __unicode__(self):
        return self.title

    def save(self, *args, **kwargs):
        if not self.user and not (self.name and self.email):  
            raise ValidationError("Anonymous review must have a name and an email")
        super(AbstractProductReview, self).save(*args, **kwargs)

    def has_votes(self):
        return self.total_votes > 0

    def num_up_votes(self):
        """Returns the total up votes"""
        return int((self.total_votes + self.delta_votes) / 2)
    
    def num_down_votes(self):
        """Returns the total down votes"""
        return int((self.total_votes - self.delta_votes) / 2)

    def update_totals(self, vote):
        """Updates total and delta votes"""
        self.total_votes += 1
        self.delta_votes += vote.delta
        self.save()
        
    def get_reviewer_name(self):
        if self.user:
            return self.user.username
        else:
            return self.name


class AbstractVote(models.Model):
    """
    Records user ratings as yes/no vote.
    * Only signed-in users can vote.
    * Each user can vote only once.
    """
    review = models.ForeignKey('reviews.ProductReview', related_name='votes')
    user = models.ForeignKey('auth.User', related_name='review_votes')
    UP, DOWN = 1, -1
    VOTE_CHOICES = (
        (UP, _("Up")),
        (DOWN, _("Down"))
    )
    delta = models.SmallIntegerField(choices=VOTE_CHOICES)
    date_created = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True
        ordering = ['-date_created']
        unique_together = (('user', 'review'),)

    def __unicode__(self):
        return u"%s vote for %s" % (self.delta, self.review)

    def save(self, *args, **kwargs):
        u"""
        Validates model and raises error if validation fails
        """
        self.review.update_totals(self)
        super(AbstractVote, self).save(*args, **kwargs)
