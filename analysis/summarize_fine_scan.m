function result=summarize_fine_scan(directory)
% SUMMARIZE_FINE_SCAN 从MATLAB自己的fine.mat计算最终统计与净峰值替代指标。
r=load(fullfile(directory,'fine.mat'));p=jsondecode(r.parameters_json);f=r.frames;s=r.spots;a=r.axial;
ref=r.reference_index;good=a(:,7)==1;ri=find(r.selected_indices==ref);zz=f(r.selected_indices,2);
peak_axial=nan(size(a));
for j=1:size(a,1)
    y=r.probes(:,j,1);[pk,i]=max(y);w=halfWidth(zz*1000,y);rv=y(ri);ties=nnz(y==pk);
    valid=all(isfinite(y)) && isfinite(w) && pk>0 && ties==1;ratio=NaN;if rv>0,ratio=pk/rv;end
    peak_axial(j,:)=[j,zz(i),w,pk,rv,ratio,double(valid),ties];
end
pg=peak_axial(:,7)==1;z=(a(:,2)-f(ref,2))*1000;zp=(peak_axial(:,2)-f(ref,2))*1000;
columns={'reference_point_id','reference_z_mm','candidates','valid_core_responses','valid_peak_responses', ...
    'reference_aperture_cv','reference_peak_cv','reference_core_cv_valid','own_max_core_cv_valid', ...
    'core_peak_z_vs_x_pearson','peak_peak_z_vs_x_pearson','core_width_vs_reference_core_pearson', ...
    'core_peak_z_vs_reference_core_pearson','roi_net_peak_to_peak_over_mean','nominal_um_per_pixel','ideal_rayleigh_um'};
stats=[f(ref,1),f(ref,2),size(s,1),nnz(good),nnz(pg),cv(s(:,8)),cv(s(:,9)),cv(a(good,5)),cv(a(good,4)), ...
    correlation(z(good),s(good,13)),correlation(zp(pg),s(pg,13)),correlation(a(good,3),a(good,5)), ...
    correlation(z(good),a(good,5)),(max(f(:,9))-min(f(:,9)))/mean(f(:,9)),p.nominal_um_per_pixel,.61*p.wavelength_um/p.objective_na];
q=[5;25;50;75;95];widths=[q,percentile(s(:,16)*p.nominal_um_per_pixel,q),percentile(s(:,17)*p.nominal_um_per_pixel,q), ...
    percentile(a(good,3),q),percentile(peak_axial(pg,3),q)];
values=unique(a(good,2));histogram=zeros(numel(values),2);
for i=1:numel(values),histogram(i,:)=[values(i),nnz(good & a(:,2)==values(i))];end
result=struct('stats',stats,'columns',{columns},'widths',widths,'histogram',histogram,'peak_axial',peak_axial, ...
    'source',r.source,'parameters_json',r.parameters_json);
save(fullfile(directory,'summary.mat'),'-struct','result','-v7');
document=cell2struct(num2cell(stats),columns,2);document.width_percentiles_columns= ...
    {'percentile','lateral_x_nominal_um','lateral_y_nominal_um','core_response_objective_um','peak_response_objective_um'};
document.width_percentiles=widths;document.core_peak_z_histogram_mm_count=histogram;
fid=fopen(fullfile(directory,'summary.json'),'w');cleanup=onCleanup(@()fclose(fid));fprintf(fid,'%s',jsonencode(document,'PrettyPrint',true));
renderFigures(r,p,directory);
end
function renderFigures(r,p,directory)
% 两种语言数值相同，图形分别使用各自原生绘图库；不逐帧归一化。
f=r.frames;ref=r.reference_index;z=(f(:,2)-f(ref,2))*1000;indices=[1,size(f,1)];
for offset=[-10,-5,-2,0,2,5,10],[~,i]=min(abs(z-offset));indices(end+1)=i;end
indices=unique(indices);fig=figure('Visible','off','Position',[100,100,1000,1000]);
for j=1:numel(indices)
    i=indices(j);subplot(3,3,j);imagesc(squeeze(r.previews(i,:,:)),[0,10]);axis image off;
    title(sprintf('ID %d; Z=%.4f mm',f(i,1),f(i,2)));
end
colormap(fig,'hot');sgtitle('Same count scale; 16x16 block means');
exportgraphics(fig,fullfile(directory,'position_images.png'),'Resolution',130);close(fig);
fig=figure('Visible','off','Position',[100,100,1000,750]);columns=[10,9,11,12];
labels={'Gradient energy / counts^2','ROI net sum / counts','Centroid x / px','Centroid y / px'};
for j=1:4
    subplot(2,2,j);plot(z,f(:,columns(j)));xlabel('Objective Z offset / um');ylabel(labels{j});
end
exportgraphics(fig,fullfile(directory,'scan_metrics.png'),'Resolution',140);close(fig);
good=r.axial(:,7)==1;xy=(r.spots(:,13:14)-mean(r.spots(:,13:14),1))*p.nominal_um_per_pixel;
fig=figure('Visible','off','Position',[100,100,1100,450]);
subplot(1,2,1);scatter(xy(good,1),xy(good,2),6,(r.axial(good,2)-f(ref,2))*1000,'filled');
axis equal;set(gca,'YDir','reverse');clim([-2,2]);colorbar;xlabel('x / nominal um');ylabel('y / nominal um');title('Core-response peak Z / objective um');
subplot(1,2,2);histogram(r.axial(good,3),40);xlabel('Core-response FWHM / objective um');ylabel('Spot count');title('Observed response, not true trap width');
exportgraphics(fig,fullfile(directory,'focus_maps.png'),'Resolution',140);close(fig);
end
function v=cv(x)
v=std(x,1)/mean(x);
end
function v=correlation(x,y)
v=NaN;if std(x,1)>0 && std(y,1)>0,c=corrcoef(x,y);v=c(1,2);end
end
function out=percentile(x,q)
x=sort(x);t=1+(numel(x)-1)*q/100;l=floor(t);u=ceil(t);out=x(l).*(u-t)+x(u).*(t-l);out(l==u)=x(l(l==u));
end
function w=halfWidth(x,y)
x=x(:);y=y(:);w=NaN;if numel(x)<3 || any(~isfinite(y)) || any(diff(x)<=0),return;end
[pk,i]=max(y);h=pk/2;if h<=0 || i==1 || i==numel(y),return;end
l=find(y(1:i-1)<=h,1,'last');rr=find(y(i+1:end)<=h,1,'first')+i;if isempty(l) || isempty(rr),return;end
xl=x(l)+(h-y(l))*(x(l+1)-x(l))/(y(l+1)-y(l));xr=x(rr-1)+(h-y(rr-1))*(x(rr)-x(rr-1))/(y(rr)-y(rr-1));w=xr-xl;
end
