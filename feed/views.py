# views.py updated to remove subtitles
from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.core.paginator import Paginator
from django.http import HttpResponse, JsonResponse
from django.template.loader import get_template
from django.views.decorators.http import require_POST, require_http_methods
from bson.errors import InvalidId
from datetime import datetime, timedelta
#from xhtml2pdf import pisa
import json
from pathlib import Path
import os

from .models import FeedItem
from .forms import FeedItemForm, FeedItemSearchForm
from .ai_services import AIWritingAssistant, AIContentEnricher, AIRecurringContentGenerator

from .ai_video_services import AIVideoGenerator
from .video_generator import TikTokVideoGenerator


# ========== VUES PRINCIPALES ==========

def feed_list(request):
    """Liste des éléments du feed avec recherche et filtres"""
    feed_items = FeedItem.objects(is_active=True)
    
    search_form = FeedItemSearchForm(request.GET)
    
    if search_form.is_valid():
        search_query = search_form.cleaned_data.get('search_query')
        if search_query:
            # Utilisation de __raw__ pour MongoDB regex
            feed_items = feed_items.filter(
                __raw__={
                    '$or': [
                        {'title': {'$regex': search_query, '$options': 'i'}},
                        {'description': {'$regex': search_query, '$options': 'i'}}
                    ]
                }
            )
        
        content_type = search_form.cleaned_data.get('content_type')
        if content_type:
            feed_items = feed_items.filter(content_type=content_type)
        
        ordering = search_form.cleaned_data.get('ordering', '-created_at')
        if ordering:
            feed_items = feed_items.order_by(ordering)
    else:
        feed_items = feed_items.order_by('-created_at')
    
    # Pagination
    feed_items_list = list(feed_items)
    paginator = Paginator(feed_items_list, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    
    # Statistiques
    stats = {
        'total_items': FeedItem.objects(is_active=True).count(),
        'content_types': len(FeedItem.objects(is_active=True).distinct('content_type')),
        'urgent_items': FeedItem.objects(
            is_active=True,
            deadline__lte=datetime.utcnow() + timedelta(days=3),
            deadline__gte=datetime.utcnow()
        ).count()
    }
    
    context = {
        'page_obj': page_obj,
        'search_form': search_form,
        'stats': stats,
        'page_title': 'Feed - Fil d\'actualité'
    }
    
    return render(request, 'feed/feed_list.html', context)


def feed_detail(request, pk):
    """Détail d'un élément du feed avec analyse IA"""
    try:
        feed_item = FeedItem.objects.get(id=pk)
    except (FeedItem.DoesNotExist, InvalidId):
        messages.error(request, '❌ Élément introuvable.')
        return redirect('feed:list')
    
    # Enrichissement IA pour l'affichage
    assistant = AIWritingAssistant()
    enricher = AIContentEnricher()
    
    # Analyse du sentiment
    sentiment = assistant.analyze_sentiment(feed_item.description)
    
    # Détection de l'émotion
    emotion = assistant.detect_emotion(feed_item.description)
    
    # Prédiction d'engagement
    engagement = assistant.predict_engagement(feed_item.description, feed_item.content_type)
    
    # Niveau d'urgence
    urgency = enricher.detect_urgency_level(feed_item.description, feed_item.deadline)
    
    # Détection de spam
    spam_check = assistant.detect_spam_likelihood(feed_item.description)
    
    # Actions à faire
    action_items = enricher.extract_action_items(feed_item.description)
    
    # Tags suggérés
    suggested_tags = enricher.suggest_tags(feed_item.description, feed_item.content_type)
    
    # CORRECTION: Passer l'user_id au template
    current_user_id = request.session.get('_auth_user_id')
    
    context = {
        'feed_item': feed_item,
        'page_title': feed_item.title,
        'current_user_id': str(current_user_id) if current_user_id else None,
        'sentiment': sentiment,
        'emotion': emotion,
        'engagement': engagement,
        'urgency': urgency,
        'spam_check': spam_check,
        'action_items': action_items,
        'suggested_tags': suggested_tags,
    }
    
    return render(request, 'feed/feed_detail.html', context)


def feed_create(request):
    """Créer un nouvel élément du feed avec assistance IA"""
    if request.method == 'POST':
        form = FeedItemForm(request.POST)
        if form.is_valid():
            user_id = request.session.get('_auth_user_id')
            
            if not user_id:
                messages.error(request, '❌ Erreur d\'authentification.')
                return redirect('accounts:login')
            
            try:
                # Sauvegarde avec enrichissement IA automatique
                feed_item = form.save(author_id=str(user_id))
                
                # Afficher les suggestions IA
                if hasattr(form, 'ai_suggestions') and form.ai_suggestions:
                    for suggestion in form.ai_suggestions[:2]:
                        messages.info(request, f"💡 {suggestion}")
                
                # Afficher le score qualité
                quality_emoji = '🌟' if feed_item.ai_quality_score >= 8 else '⭐'
                messages.success(
                    request,
                    f'✅ Élément "{feed_item.title}" créé avec succès ! '
                    f'{quality_emoji} Score qualité: {feed_item.ai_quality_score:.1f}/10'
                )
                
                return redirect('feed:detail', pk=str(feed_item.id))
                
            except Exception as e:
                messages.error(request, f'❌ Erreur lors de la sauvegarde: {str(e)}')
                print(f"ERROR feed_create: {e}")
                import traceback
                traceback.print_exc()
        else:
            messages.error(request, '❌ Veuillez corriger les erreurs dans le formulaire.')
    else:
        form = FeedItemForm()
    
    context = {
        'form': form,
        'action': 'Créer',
        'page_title': 'Créer un élément du feed'
    }
    
    return render(request, 'feed/feed_form.html', context)


def feed_update(request, pk):
    """Modifier un élément du feed"""
    try:
        feed_item = FeedItem.objects.get(id=pk)
    except (FeedItem.DoesNotExist, InvalidId):
        messages.error(request, '❌ Élément introuvable.')
        return redirect('feed:list')
    
    # Vérification des permissions
    user_id = request.session.get('_auth_user_id')
    if str(feed_item.author_id) != str(user_id):
        messages.error(request, '❌ Vous n\'avez pas la permission de modifier cet élément.')
        return redirect('feed:detail', pk=pk)
    
    if request.method == 'POST':
        form = FeedItemForm(request.POST)
        if form.is_valid():
            try:
                # Mise à jour des champs
                feed_item.title = form.cleaned_data['title']
                feed_item.description = form.cleaned_data['description']
                feed_item.content_type = form.cleaned_data['content_type']
                feed_item.deadline = form.cleaned_data.get('deadline')
                feed_item.is_active = form.cleaned_data.get('is_active', True)
                
                # Réappliquer l'enrichissement IA
                assistant = AIWritingAssistant()
                enricher = AIContentEnricher()
                
                # Suggestions d'amélioration
                feed_item.ai_suggestions = assistant.suggest_improvements(
                    feed_item.description, 
                    feed_item.content_type
                )
                
                # Extraction de dates
                extracted_dates = enricher.extract_dates(feed_item.description)
                feed_item.ai_extracted_dates = [d['text'] for d in extracted_dates]
                
                # Ressources suggérées
                feed_item.suggested_resources = enricher.suggest_resources(
                    feed_item.description,
                    feed_item.content_type
                )
                
                # Recalculer le score qualité
                feed_item.ai_quality_score = assistant.calculate_quality_score(
                    feed_item.description,
                    feed_item.content_type
                )
                
                # Détecter le ton
                description_lower = feed_item.description.lower()
                if 'urgent' in description_lower or 'immédiat' in description_lower:
                    feed_item.ai_tone = 'urgent'
                elif any(word in description_lower for word in ['merci', 'cordialement', 'veuillez']):
                    feed_item.ai_tone = 'formel'
                else:
                    feed_item.ai_tone = 'informatif'
                
                feed_item.save()
                
                messages.success(
                    request, 
                    f'✅ Élément "{feed_item.title}" modifié avec succès ! '
                    f'Score: {feed_item.ai_quality_score:.1f}/10'
                )
                return redirect('feed:detail', pk=str(feed_item.id))
                
            except Exception as e:
                messages.error(request, f'❌ Erreur lors de la modification: {str(e)}')
                print(f"ERROR feed_update: {e}")
        else:
            messages.error(request, '❌ Veuillez corriger les erreurs dans le formulaire.')
    else:
        # Pré-remplir le formulaire
        initial_data = {
            'title': feed_item.title,
            'description': feed_item.description,
            'content_type': feed_item.content_type,
            'deadline': feed_item.deadline,
            'is_active': feed_item.is_active,
        }
        form = FeedItemForm(initial=initial_data)
    
    context = {
        'form': form,
        'feed_item': feed_item,
        'action': 'Modifier',
        'page_title': f'Modifier: {feed_item.title}'
    }
    
    return render(request, 'feed/feed_form.html', context)


def feed_delete(request, pk):
    """Supprimer un élément du feed"""
    try:
        feed_item = FeedItem.objects.get(id=pk)
    except (FeedItem.DoesNotExist, InvalidId):
        messages.error(request, '❌ Élément introuvable.')
        return redirect('feed:list')
    
    # Vérification des permissions
    user_id = request.session.get('_auth_user_id')
    if str(feed_item.author_id) != str(user_id):
        messages.error(request, '❌ Vous n\'avez pas la permission de supprimer cet élément.')
        return redirect('feed:detail', pk=pk)
    
    if request.method == 'POST':
        title = feed_item.title
        feed_item.delete()
        messages.success(request, f'✅ Élément "{title}" supprimé avec succès.')
        return redirect('feed:list')
    
    context = {
        'feed_item': feed_item,
        'page_title': f'Supprimer: {feed_item.title}'
    }
    
    return render(request, 'feed/feed_confirm_delete.html', context)


def feed_export_pdf(request):
    """Exporte la liste des feed items en PDF"""
    feed_items = FeedItem.objects(is_active=True)
    
    search_form = FeedItemSearchForm(request.GET)
    
    if search_form.is_valid():
        search_query = search_form.cleaned_data.get('search_query')
        if search_query:
            feed_items = feed_items.filter(
                __raw__={
                    '$or': [
                        {'title': {'$regex': search_query, '$options': 'i'}},
                        {'description': {'$regex': search_query, '$options': 'i'}}
                    ]
                }
            )
        
        content_type = search_form.cleaned_data.get('content_type')
        if content_type:
            feed_items = feed_items.filter(content_type=content_type)
        
        ordering = search_form.cleaned_data.get('ordering', '-created_at')
        if ordering:
            feed_items = feed_items.order_by(ordering)
    
    context = {
        'feed_items': list(feed_items),
        'stats': {
            'total_items': feed_items.count(),
            'export_date': datetime.now().strftime('%d/%m/%Y %H:%M')
        },
        'page_title': 'Export PDF - Feed'
    }
    
    # ✅ Retourne un message simple - PDF désactivé temporairement
    messages.info(request, '⚠️ Fonctionnalité PDF temporairement désactivée - En cours de maintenance')
    return redirect('feed:list')


# ========== FONCTIONNALITÉS IA AVANCÉES ==========

def ai_check_content(request):
    """
    API AJAX pour vérifier le contenu en temps réel
    Retourne: suggestions grammaticales, améliorations, dates extraites, ton
    """
    try:
        text = request.POST.get('text', '')
        content_type = request.POST.get('content_type', 'programme')
        
        if not text or len(text) < 5:
            return JsonResponse({
                'success': False, 
                'error': 'Texte trop court ou vide'
            })
        
        # Initialiser les services IA
        assistant = AIWritingAssistant()
        enricher = AIContentEnricher()
        
        # Vérifications grammaticales
        grammar_issues = assistant.check_grammar(text)
        
        # Suggestions d'amélioration
        improvements = assistant.suggest_improvements(text, content_type)
        
        # Extraction de dates
        extracted_dates = enricher.extract_dates(text)
        
        # Vérification du ton
        tone_suggestion = assistant._check_tone(text, content_type)
        
        # Analyse de sentiment
        sentiment = assistant.analyze_sentiment(text)
        
        # Prédiction d'engagement
        engagement = assistant.predict_engagement(text, content_type)
        
        # Score qualité
        quality_score = assistant.calculate_quality_score(text, content_type)
        
        # Correction automatique
        auto_correct = assistant.auto_correct_common_errors(text)
        
        return JsonResponse({
            'success': True,
            'grammar_issues': grammar_issues[:5],
            'improvements': improvements,
            'extracted_dates': [d['text'] for d in extracted_dates],
            'tone_suggestion': tone_suggestion,
            'sentiment': sentiment,
            'engagement': engagement,
            'quality_score': quality_score,
            'auto_correct': auto_correct,
            'stats': {
                'length': len(text),
                'words': len(text.split()),
                'sentences': text.count('.') + text.count('!') + text.count('?')
            }
        })
        
    except Exception as e:
        print(f"ERROR ai_check_content: {e}")
        import traceback
        traceback.print_exc()
        return JsonResponse({
            'success': False, 
            'error': f'Erreur serveur: {str(e)}'
        }, status=500)


def generate_weekly_summary(request):
    """
    Génère et publie automatiquement un résumé hebdomadaire
    des activités du feed
    """
    try:
        # Récupérer les posts de la semaine dernière
        week_ago = datetime.utcnow() - timedelta(days=7)
        feed_items = list(FeedItem.objects(
            created_at__gte=week_ago, 
            is_active=True
        ))
        
        generator = AIRecurringContentGenerator()
        summary_data = generator.generate_weekly_summary(feed_items)
        
        if summary_data:
            # Créer le post de résumé
            user_id = request.session.get('_auth_user_id')
            
            if not user_id:
                messages.error(request, '❌ Erreur d\'authentification.')
                return redirect('accounts:login')
            
            # ✅ CORRECTION: Retirer ai_quality_score du dictionnaire pour l'ajouter séparément
            ai_score = summary_data.pop('ai_quality_score', None)  # Retirer du dict
            ai_tone_value = summary_data.pop('ai_tone', None)      # Retirer du dict
            
            # Créer l'objet sans duplication
            summary_item = FeedItem(
                **summary_data,  # Spread le reste des données
                author_id=str(user_id),
                ai_quality_score=ai_score or 8.0,  # Ajouter séparément
                ai_tone=ai_tone_value or 'informatif'  # Ajouter séparément
            )
            summary_item.save()
            
            messages.success(
                request, 
                f'📊 Résumé hebdomadaire généré et publié avec succès ! '
                f'({len(feed_items)} élément(s) analysé(s))'
            )
        else:
            messages.warning(
                request, 
                'ℹ️ Aucune activité à résumer pour cette semaine.'
            )
        
        return redirect('feed:list')
        
    except Exception as e:
        messages.error(request, f'❌ Erreur lors de la génération: {str(e)}')
        print(f"ERROR generate_weekly_summary: {e}")
        import traceback
        traceback.print_exc()
        return redirect('feed:list')


def check_missing_content(request):
    """
    Vérifie et affiche les types de contenu manquants
    sur les 7 derniers jours
    """
    try:
        # Récupérer les posts de la semaine
        week_ago = datetime.utcnow() - timedelta(days=7)
        feed_items = list(FeedItem.objects(
            created_at__gte=week_ago, 
            is_active=True
        ))
        
        generator = AIRecurringContentGenerator()
        missing_suggestions = generator.detect_missing_content(feed_items, days=7)
        
        # Statistiques supplémentaires
        content_distribution = {}
        for item in feed_items:
            content_distribution[item.content_type] = content_distribution.get(item.content_type, 0) + 1
        
        context = {
            'suggestions': missing_suggestions,
            'feed_items_count': len(feed_items),
            'content_distribution': content_distribution,
            'analysis_period': '7 derniers jours',
            'page_title': 'Analyse des contenus manquants'
        }
        
        return render(request, 'feed/missing_content.html', context)
        
    except Exception as e:
        messages.error(request, f'❌ Erreur lors de l\'analyse: {str(e)}')
        print(f"ERROR check_missing_content: {e}")
        return redirect('feed:list')


def generate_deadline_reminders(request):
    """
    Génère automatiquement des rappels pour toutes les échéances
    proches (dans les 3 prochains jours)
    """
    try:
        # Items avec deadline dans les 3 prochains jours
        now = datetime.utcnow()
        upcoming_deadline = now + timedelta(days=3)
        
        feed_items = FeedItem.objects(
            deadline__lte=upcoming_deadline,
            deadline__gte=now,
            is_active=True
        )
        
        generator = AIRecurringContentGenerator()
        reminders_created = 0
        user_id = request.session.get('_auth_user_id')
        
        if not user_id:
            messages.error(request, '❌ Erreur d\'authentification.')
            return redirect('accounts:login')
        
        # Générer un rappel pour chaque échéance
        for item in feed_items:
            reminder_data = generator.generate_deadline_reminder(item)
            
            if reminder_data:
                # Vérifier qu'un rappel n'existe pas déjà
                existing_reminder = FeedItem.objects(
                    title__icontains=item.title,
                    is_ai_generated=True,
                    created_at__gte=now - timedelta(days=1)
                ).first()
                
                if not existing_reminder:
                    reminder = FeedItem(
                        **reminder_data,
                        author_id=str(user_id),
                        ai_quality_score=7.5,
                        ai_tone='urgent'
                    )
                    reminder.save()
                    reminders_created += 1
        
        if reminders_created > 0:
            messages.success(
                request, 
                f'✅ {reminders_created} rappel(s) d\'échéance créé(s) avec succès !'
            )
        else:
            messages.info(
                request, 
                'ℹ️ Aucune échéance urgente à signaler ou rappels déjà créés.'
            )
        
        return redirect('feed:list')
        
    except Exception as e:
        messages.error(request, f'❌ Erreur lors de la génération: {str(e)}')
        print(f"ERROR generate_deadline_reminders: {e}")
        import traceback
        traceback.print_exc()
        return redirect('feed:list')


# ========== VUES IA AVANCÉES SUPPLÉMENTAIRES ==========

def ai_analyze_content(request):
    """
    Analyse complète d'un contenu existant (AJAX)
    Retourne: sentiment, émotion, engagement, urgence, spam, etc.
    """
    try:
        content_id = request.POST.get('content_id')
        
        if not content_id:
            return JsonResponse({'success': False, 'error': 'ID manquant'})
        
        feed_item = FeedItem.objects.get(id=content_id)
        
        assistant = AIWritingAssistant()
        enricher = AIContentEnricher()
        
        # Analyses complètes
        sentiment = assistant.analyze_sentiment(feed_item.description)
        emotion = assistant.detect_emotion(feed_item.description)
        engagement = assistant.predict_engagement(feed_item.description, feed_item.content_type)
        urgency = enricher.detect_urgency_level(feed_item.description, feed_item.deadline)
        spam_check = assistant.detect_spam_likelihood(feed_item.description)
        action_items = enricher.extract_action_items(feed_item.description)
        tags = enricher.suggest_tags(feed_item.description, feed_item.content_type)
        
        return JsonResponse({
            'success': True,
            'sentiment': sentiment,
            'emotion': emotion,
            'engagement': engagement,
            'urgency': urgency,
            'spam_check': spam_check,
            'action_items': action_items,
            'tags': tags
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def ai_suggest_title(request):
    """
    Suggère des titres accrocheurs basés sur la description (AJAX)
    """
    try:
        description = request.POST.get('description', '')
        content_type = request.POST.get('content_type', 'programme')
        
        if not description or len(description) < 10:
            return JsonResponse({
                'success': False, 
                'error': 'Description trop courte'
            })
        
        assistant = AIWritingAssistant()
        titles = assistant.suggest_title(description, content_type)
        
        return JsonResponse({
            'success': True,
            'suggested_titles': titles
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def ai_dashboard(request):
    """
    Tableau de bord IA avec statistiques et analyses globales
    """
    try:
        # Récupérer tous les items
        all_items = list(FeedItem.objects(is_active=True))
        
        assistant = AIWritingAssistant()
        
        # Statistiques globales
        total_items = len(all_items)
        avg_quality = sum(item.ai_quality_score for item in all_items) / total_items if total_items > 0 else 0
        
        # Distribution par type
        type_distribution = {}
        for item in all_items:
            type_distribution[item.content_type] = type_distribution.get(item.content_type, 0) + 1
        
        # Distribution par ton
        tone_distribution = {}
        for item in all_items:
            tone = item.ai_tone or 'non défini'
            tone_distribution[tone] = tone_distribution.get(tone, 0) + 1
        
        # Items avec meilleur score
        top_quality_items = sorted(all_items, key=lambda x: x.ai_quality_score, reverse=True)[:5]
        
        # Items urgents
        urgent_items = [item for item in all_items if item.is_urgent()]
        
        context = {
            'total_items': total_items,
            'avg_quality': round(avg_quality, 1),
            'type_distribution': type_distribution,
            'tone_distribution': tone_distribution,
            'top_quality_items': top_quality_items,
            'urgent_items': urgent_items,
            'page_title': '🤖 Tableau de bord IA'
        }
        
        return render(request, 'feed/ai_dashboard.html', context)
        
    except Exception as e:
        messages.error(request, f'❌ Erreur: {str(e)}')
        return redirect('feed:list')


def generate_tiktok_video(request, pk):
    """Génère une vidéo TikTok à partir d'un post"""
    try:
        feed_item = FeedItem.objects.get(id=pk)
    except (FeedItem.DoesNotExist, InvalidId):
        messages.error(request, '❌ Élément introuvable.')
        return redirect('feed:list')
    
    if request.method == 'POST':
        try:
            print(f"\n{'='*50}")
            print(f"🎬 GÉNÉRATION VIDÉO TIKTOK - {feed_item.title}")
            print(f"{'='*50}\n")
            
            # Statut processing
            feed_item.tiktok_video_status = 'processing'
            feed_item.save()
            
            # Créer dossier temp
            from django.conf import settings
            temp_dir = Path(settings.MEDIA_ROOT) / 'temp_video'
            temp_dir.mkdir(parents=True, exist_ok=True)
            
            # 1. Script
            print("1️⃣ Génération du script...")
            video_gen = AIVideoGenerator()
            script_result = video_gen.generate_tiktok_script(feed_item)
            
            if not script_result['success']:
                raise Exception(f"Erreur script: {script_result['error']}")
            
            script = script_result['script']
            print(f"✅ Script ({script_result['word_count']} mots):\n{script[:100]}...\n")
            
            # 2. Audio
            print("2️⃣ Génération audio...")
            audio_path = temp_dir / f"audio_{pk}.mp3"
            audio_result = video_gen.generate_audio(script, str(audio_path))
            
            if not audio_result['success']:
                raise Exception(f"Erreur audio: {audio_result['error']}")
            print(f"✅ Audio généré: {audio_path}\n")
            
            # Skip subtitles as per request
            
            # 4. Vidéo
            print("3️⃣ Assemblage vidéo (sans sous-titres)...")
            video_generator = TikTokVideoGenerator()
            video_result = video_generator.generate_video(
                feed_item,
                script,
                str(audio_path),
                None  # No subtitles
            )
            
            if not video_result['success']:
                raise Exception(f"Erreur vidéo: {video_result['error']}")
            
            # 5. Mise à jour modèle
            video_path = video_result['video_path']
            video_filename = Path(video_path).name
            video_url = f"/media/feed_videos/{video_filename}"
            
            feed_item.tiktok_video_url = video_url
            feed_item.tiktok_video_status = 'completed'
            feed_item.tiktok_generation_date = datetime.utcnow()
            feed_item.tiktok_metadata = {
                'script': script,
                'duration': video_result['duration'],
                'word_count': script_result['word_count'],
                'model': script_result['model']
            }
            feed_item.save()
            
            # Nettoyage
            try:
                os.remove(audio_path)
            except:
                pass
            
            print(f"\n✅ VIDÉO GÉNÉRÉE AVEC SUCCÈS!")
            print(f"📹 URL: {video_url}")
            print(f"⏱️ Durée: {video_result['duration']:.1f}s\n")
            
            messages.success(request, f'🎉 Vidéo TikTok générée avec succès ! (Durée: {video_result["duration"]:.0f}s)')
            return redirect('feed:detail', pk=str(feed_item.id))
            
        except Exception as e:
            feed_item.tiktok_video_status = 'failed'
            feed_item.save()
            
            print(f"\n❌ ERREUR: {str(e)}\n")
            import traceback
            traceback.print_exc()
            
            messages.error(request, f'❌ Erreur: {str(e)}')
            return redirect('feed:detail', pk=str(feed_item.id))
    
    # GET: Afficher confirmation
    context = {
        'feed_item': feed_item,
        'page_title': 'Générer Vidéo TikTok'
    }
    return render(request, 'feed/generate_tiktok_confirm.html', context)